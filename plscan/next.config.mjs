/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'dd.dexscreener.com' }
    ]
  }
};
export default nextConfig;
