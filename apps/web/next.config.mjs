/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Proxy every /api/* and /health/* request from the browser to the api
  // container. The browser always hits the web server's origin, so the user
  // can change API_PORT / WEB_PORT in .env without rebuilding the frontend,
  // and CORS stops being a concern — everything is same-origin.
  //
  // The target uses the docker-compose service name `api` and its internal
  // port 8000. Outside Docker, set INTERNAL_API_URL to point at your api.
  async rewrites() {
    const target = process.env.INTERNAL_API_URL || "http://api:8000";
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
      { source: "/health/:path*", destination: `${target}/health/:path*` },
    ];
  },
};

export default nextConfig;
