import pytest

from documind.core.config import Backend, LLMProviderName, Settings
from documind.core.container import Container, build_container
from tests.pdf_factory import make_pdf


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # never read a developer's local .env
        backend=Backend.MEMORY,
        llm_provider=LLMProviderName.FAKE,
        chunk_size=200,
        chunk_overlap=30,
        retrieval_top_k=3,
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    return build_container(settings)


@pytest.fixture
def sample_pdf() -> bytes:
    return make_pdf(
        [
            "Acme Corp Annual Report 2025\nRevenue grew 12 percent to 4.2 billion dollars.",
            "The company employs 3,100 people across 14 countries.\n"
            "Headquarters are located in Toronto, Canada.",
            "Risk factors include currency fluctuations and supply chain delays.",
        ]
    )
