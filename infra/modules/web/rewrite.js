// CloudFront Function (viewer request). The Next.js static export writes each page as
// <route>/index.html, but S3 has no "directory index" when accessed through CloudFront, so map
// /chat/ and /chat to /chat/index.html. Files with an extension pass through unchanged.
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith("/")) {
    request.uri = uri + "index.html";
  } else if (uri.split("/").pop().indexOf(".") === -1) {
    request.uri = uri + "/index.html";
  }
  return request;
}
