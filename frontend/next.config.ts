import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Plain HTML/CSS/JS in out/, served from S3 + CloudFront; no server to run or pay for.
  output: "export",
  // /chat → /chat/index.html, which S3 can serve without rewrite rules.
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
