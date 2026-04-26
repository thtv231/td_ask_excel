/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config) => {
    // Force @huggingface/transformers to use WASM backend instead of
    // native onnxruntime-node bindings (not available on Vercel serverless)
    config.resolve.alias = {
      ...config.resolve.alias,
      "sharp$": false,
      "onnxruntime-node$": false,
    };
    return config;
  },
};

export default nextConfig;
