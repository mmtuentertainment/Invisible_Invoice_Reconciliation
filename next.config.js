/** @type {import('next').NextConfig} */

const withBundleAnalyzer = require('@next/bundle-analyzer')({
  enabled: process.env.ANALYZE === 'true',
});

const nextConfig = {
  // Basic configuration
  reactStrictMode: true,
  swcMinify: true,
  
  // Experimental features for React 19 and Next.js 15
  experimental: {
    serverComponentsExternalPackages: ['@supabase/supabase-js'],
    turbo: {
      rules: {
        '*.svg': {
          loaders: ['@svgr/webpack'],
          as: '*.js',
        },
      },
    },
  },

  // TypeScript configuration
  typescript: {
    tsconfigPath: './tsconfig.json',
  },

  // Environment variables
  env: {
    API_VERSION: process.env.API_VERSION || '1.0.0',
  },

  // Public runtime config
  publicRuntimeConfig: {
    appUrl: process.env.NEXT_PUBLIC_APP_URL,
    supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL,
  },

  // Image optimization
  images: {
    domains: [
      'localhost',
      '*.supabase.co',
      'avatars.githubusercontent.com',
    ],
    formats: ['image/webp', 'image/avif'],
    dangerouslyAllowSVG: true,
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
  },

  // Security headers
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'X-XSS-Protection',
            value: '1; mode=block',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
        ],
      },
      {
        source: '/api/(.*)',
        headers: [
          {
            key: 'Access-Control-Allow-Origin',
            value: process.env.NODE_ENV === 'development' 
              ? '*' 
              : process.env.NEXT_PUBLIC_APP_URL || 'https://invoice-recon.com',
          },
          {
            key: 'Access-Control-Allow-Methods',
            value: 'GET, POST, PUT, DELETE, OPTIONS',
          },
          {
            key: 'Access-Control-Allow-Headers',
            value: 'Content-Type, Authorization, Idempotency-Key',
          },
          {
            key: 'Access-Control-Max-Age',
            value: '86400', // 24 hours
          },
        ],
      },
    ];
  },

  // Redirects
  async redirects() {
    return [
      {
        source: '/docs',
        destination: '/api-docs',
        permanent: false,
      },
      {
        source: '/health',
        destination: '/api/health',
        permanent: false,
      },
    ];
  },

  // Rewrites for API documentation
  async rewrites() {
    return [
      {
        source: '/api-docs',
        destination: '/api/docs',
      },
      {
        source: '/openapi.json',
        destination: '/api/openapi',
      },
    ];
  },

  // Webpack configuration
  webpack: (config, { buildId, dev, isServer, defaultLoaders, webpack }) => {
    // Bundle analyzer
    if (process.env.ANALYZE === 'true') {
      config.plugins.push(
        new webpack.ProgressPlugin((percentage, message, ...args) => {
          console.info(`${(percentage * 100).toFixed(2)}%`, message, ...args);
        })
      );
    }

    // SVG handling
    config.module.rules.push({
      test: /\.svg$/i,
      issuer: /\.[jt]sx?$/,
      use: ['@svgr/webpack'],
    });

    // Development optimizations
    if (dev && !isServer) {
      config.devtool = 'eval-source-map';
    }

    // Production optimizations
    if (!dev) {
      config.optimization = {
        ...config.optimization,
        splitChunks: {
          chunks: 'all',
          cacheGroups: {
            default: {
              minChunks: 2,
              priority: -20,
              reuseExistingChunk: true,
            },
            vendor: {
              test: /[\\/]node_modules[\\/]/,
              name: 'vendors',
              priority: -10,
              chunks: 'all',
            },
            supabase: {
              test: /[\\/]node_modules[\\/]@supabase[\\/]/,
              name: 'supabase',
              priority: 10,
              chunks: 'all',
            },
            react: {
              test: /[\\/]node_modules[\\/](react|react-dom)[\\/]/,
              name: 'react',
              priority: 20,
              chunks: 'all',
            },
          },
        },
      };
    }

    return config;
  },

  // Output file tracing
  output: 'standalone',

  // Compiler options
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production' ? {
      exclude: ['error', 'warn'],
    } : false,
  },

  // ESLint configuration
  eslint: {
    dirs: ['app', 'components', 'lib', 'types'],
    ignoreDuringBuilds: false,
  },

  // PoweredByHeader
  poweredByHeader: false,

  // Compression
  compress: true,

  // Generate ETags for static assets
  generateEtags: true,

  // HTTP Keepalive
  httpAgentOptions: {
    keepAlive: true,
  },

  // Static file serving
  assetPrefix: process.env.NODE_ENV === 'production' 
    ? process.env.NEXT_PUBLIC_CDN_URL 
    : undefined,

  // Error handling
  onDemandEntries: {
    maxInactiveAge: 25 * 1000,
    pagesBufferLength: 2,
  },

  // Development specific
  ...(process.env.NODE_ENV === 'development' && {
    async rewrites() {
      return [
        {
          source: '/api-docs',
          destination: '/api/docs',
        },
        {
          source: '/openapi.json',
          destination: '/api/openapi',
        },
        // Proxy Supabase in development
        {
          source: '/supabase/:path*',
          destination: `${process.env.NEXT_PUBLIC_SUPABASE_URL}/:path*`,
        },
      ];
    },
  }),
};

module.exports = withBundleAnalyzer(nextConfig);