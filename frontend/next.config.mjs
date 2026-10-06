/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `next build` and `next dev` both write to .next by default, so running a build
  // while the dev server is up leaves dev serving a half-replaced cache and failing
  // with "Cannot find module './NNN.js'". Give the production build its own directory.
  distDir: process.env.NODE_ENV === "production" ? ".next-build" : ".next",
  poweredByHeader: false,
  // The browser never talks to FastAPI directly. Requests go through the route handler
  // at /api/proxy/[...path], which moves the session token from an httpOnly cookie into
  // the Authorization header. API_INTERNAL_URL is the server-side address of the API
  // (http://api:8000 under Docker Compose).
  env: {
    NEXT_PUBLIC_APP_NAME: "PumpAtlas AI",
  },
};

export default nextConfig;
