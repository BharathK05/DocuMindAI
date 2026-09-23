"""Create the DynamoDB table, S3 bucket and SQS queues on the local emulators (idempotent).

In AWS these resources are created by Terraform (Phase 5); this script mirrors that shape so
local dev behaves the same. Run: ``python -m documind.scripts.bootstrap_local``.
"""

import json
import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

from documind.core.config import Settings, get_settings
from documind.core.logging import configure_logging

logger = logging.getLogger(__name__)


def _client(service: str, settings: Settings, endpoint_url: str | None) -> Any:
    return boto3.client(service, region_name=settings.aws_region, endpoint_url=endpoint_url)  # type: ignore[call-overload]


def _create_table(settings: Settings) -> None:
    dynamodb = _client("dynamodb", settings, settings.dynamodb_endpoint_url)
    try:
        dynamodb.create_table(
            TableName=settings.dynamodb_table,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceInUseException":
            raise


def _create_bucket(settings: Settings) -> None:
    s3 = _client("s3", settings, settings.s3_endpoint_url)
    try:
        s3.create_bucket(Bucket=settings.s3_bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise
    # Browsers POST uploads straight to the bucket, so it must allow the frontend's origin.
    s3.put_bucket_cors(
        Bucket=settings.s3_bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": settings.cors_origins,
                    "AllowedMethods": ["POST"],
                    "AllowedHeaders": ["*"],
                    "MaxAgeSeconds": 3000,
                }
            ]
        },
    )


def _create_queues(settings: Settings) -> None:
    sqs = _client("sqs", settings, settings.sqs_endpoint_url)
    dlq_url = sqs.create_queue(QueueName=f"{settings.sqs_queue_name}-dlq")["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    sqs.create_queue(
        QueueName=settings.sqs_queue_name,
        Attributes={
            # Must exceed the worst-case ingestion time, or a slow job gets processed twice.
            "VisibilityTimeout": "300",
            "RedrivePolicy": json.dumps(
                {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": settings.sqs_max_receive_count}
            ),
        },
    )


def bootstrap(settings: Settings) -> None:
    _create_table(settings)
    _create_bucket(settings)
    _create_queues(settings)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    for attempt in range(30):  # emulators may still be starting when compose runs us
        try:
            bootstrap(settings)
            break
        except (EndpointConnectionError, ConnectionError):
            logger.info("waiting for emulators", extra={"attempt": attempt})
            time.sleep(2)
    else:
        raise SystemExit("Local AWS emulators never became reachable.")
    logger.info("local resources ready")


if __name__ == "__main__":
    main()
