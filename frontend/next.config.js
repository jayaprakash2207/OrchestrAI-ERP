/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  pageExtensions: ["js", "jsx"],
  experimental: {
    typedRoutes: true
  }
};

module.exports = nextConfig;
