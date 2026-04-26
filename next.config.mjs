/** @type {import('next').NextConfig} */
const nextConfig = {
  // Exclude heavy native packages from webpack bundling so that
  // onnxruntime-node binaries and ONNX WASM files stay on disk.
  experimental: {
    serverComponentsExternalPackages: [
      "@huggingface/transformers",
      "onnxruntime-node",
      "sharp",
    ],
  },
};

export default nextConfig;
