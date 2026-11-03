const nextConfig = {
  experimental: {
    cpus: 1,
  },
}

if (process.env.NEXT_EXPORT) {
  nextConfig.output = 'export'
  nextConfig.distDir = 'out'
  nextConfig.trailingSlash = true
  nextConfig.assetPrefix = process.env.ASSET_PREFIX || undefined
}

module.exports = nextConfig
