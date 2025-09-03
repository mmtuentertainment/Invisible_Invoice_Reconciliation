/** @type {import('tailwindcss').Config} */

const { fontFamily } = require('tailwindcss/defaultTheme');

module.exports = {
  darkMode: ['class'],
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        // Custom colors for invoice reconciliation
        success: {
          DEFAULT: 'hsl(142, 76%, 36%)',
          foreground: 'hsl(355, 7%, 97%)',
        },
        warning: {
          DEFAULT: 'hsl(38, 92%, 50%)',
          foreground: 'hsl(48, 96%, 89%)',
        },
        info: {
          DEFAULT: 'hsl(199, 89%, 48%)',
          foreground: 'hsl(210, 40%, 98%)',
        },
        // Status colors for matching
        matched: {
          DEFAULT: 'hsl(142, 76%, 36%)',
          light: 'hsl(138, 62%, 47%)',
          foreground: 'hsl(355, 7%, 97%)',
        },
        exception: {
          DEFAULT: 'hsl(0, 84%, 60%)',
          light: 'hsl(0, 93%, 94%)',
          foreground: 'hsl(210, 40%, 98%)',
        },
        pending: {
          DEFAULT: 'hsl(38, 92%, 50%)',
          light: 'hsl(48, 96%, 89%)',
          foreground: 'hsl(26, 83%, 14%)',
        },
        processing: {
          DEFAULT: 'hsl(217, 91%, 60%)',
          light: 'hsl(214, 95%, 93%)',
          foreground: 'hsl(210, 40%, 98%)',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: ['var(--font-sans)', ...fontFamily.sans],
        mono: ['var(--font-mono)', ...fontFamily.mono],
      },
      keyframes: {
        'accordion-down': {
          from: { height: 0 },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: 0 },
        },
        // Custom animations
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'fade-out': {
          '0%': { opacity: '1' },
          '100%': { opacity: '0' },
        },
        'slide-in-from-top': {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(0)' },
        },
        'slide-in-from-bottom': {
          '0%': { transform: 'translateY(100%)' },
          '100%': { transform: 'translateY(0)' },
        },
        'slide-in-from-left': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        'slide-in-from-right': {
          '0%': { transform: 'translateX(100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        'pulse-slow': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
        'spin-slow': {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
        'bounce-subtle': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4px)' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'fade-in': 'fade-in 0.2s ease-out',
        'fade-out': 'fade-out 0.2s ease-out',
        'slide-in-from-top': 'slide-in-from-top 0.3s ease-out',
        'slide-in-from-bottom': 'slide-in-from-bottom 0.3s ease-out',
        'slide-in-from-left': 'slide-in-from-left 0.3s ease-out',
        'slide-in-from-right': 'slide-in-from-right 0.3s ease-out',
        'pulse-slow': 'pulse-slow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow': 'spin-slow 3s linear infinite',
        'bounce-subtle': 'bounce-subtle 1s ease-in-out infinite',
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        '128': '32rem',
      },
      maxWidth: {
        '8xl': '88rem',
        '9xl': '96rem',
      },
      minHeight: {
        'screen-75': '75vh',
        'screen-80': '80vh',
        'screen-90': '90vh',
      },
      zIndex: {
        '60': '60',
        '70': '70',
        '80': '80',
        '90': '90',
        '100': '100',
      },
      backdropBlur: {
        xs: '2px',
      },
      boxShadow: {
        'soft': '0 2px 8px 0 rgba(0, 0, 0, 0.05)',
        'medium': '0 4px 12px 0 rgba(0, 0, 0, 0.1)',
        'hard': '0 8px 24px 0 rgba(0, 0, 0, 0.15)',
        'glow': '0 0 20px 0 rgba(59, 130, 246, 0.3)',
      },
      dropShadow: {
        'soft': '0 2px 4px rgba(0, 0, 0, 0.05)',
        'glow': '0 0 10px rgba(59, 130, 246, 0.3)',
      },
    },
  },
  plugins: [
    require('tailwindcss-animate'),
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
    // Custom plugin for utilities
    function({ addUtilities, addComponents, theme }) {
      addUtilities({
        '.text-shadow': {
          textShadow: '2px 2px 4px rgba(0,0,0,0.10)',
        },
        '.text-shadow-md': {
          textShadow: '4px 4px 8px rgba(0,0,0,0.12)',
        },
        '.text-shadow-lg': {
          textShadow: '15px 15px 30px rgba(0,0,0,0.11)',
        },
        '.text-shadow-none': {
          textShadow: 'none',
        },
        '.scrollbar-thin': {
          scrollbarWidth: 'thin',
        },
        '.scrollbar-none': {
          scrollbarWidth: 'none',
          '&::-webkit-scrollbar': {
            display: 'none',
          },
        },
      });

      addComponents({
        '.btn-primary': {
          backgroundColor: theme('colors.primary.DEFAULT'),
          color: theme('colors.primary.foreground'),
          padding: `${theme('spacing.2')} ${theme('spacing.4')}`,
          borderRadius: theme('borderRadius.md'),
          fontWeight: theme('fontWeight.medium'),
          '&:hover': {
            backgroundColor: theme('colors.primary.DEFAULT'),
            opacity: '0.9',
          },
          '&:focus': {
            outline: 'none',
            boxShadow: `0 0 0 2px ${theme('colors.ring')}`,
          },
          '&:disabled': {
            opacity: '0.5',
            cursor: 'not-allowed',
          },
        },
        '.btn-secondary': {
          backgroundColor: theme('colors.secondary.DEFAULT'),
          color: theme('colors.secondary.foreground'),
          padding: `${theme('spacing.2')} ${theme('spacing.4')}`,
          borderRadius: theme('borderRadius.md'),
          fontWeight: theme('fontWeight.medium'),
          '&:hover': {
            backgroundColor: theme('colors.secondary.DEFAULT'),
            opacity: '0.8',
          },
        },
        '.card-hover': {
          transition: 'all 0.2s ease-in-out',
          '&:hover': {
            transform: 'translateY(-2px)',
            boxShadow: theme('boxShadow.medium'),
          },
        },
        '.status-badge': {
          display: 'inline-flex',
          alignItems: 'center',
          padding: `${theme('spacing.1')} ${theme('spacing.2')}`,
          borderRadius: theme('borderRadius.full'),
          fontSize: theme('fontSize.xs'),
          fontWeight: theme('fontWeight.medium'),
          textTransform: 'uppercase',
          letterSpacing: theme('letterSpacing.wider'),
        },
        '.status-matched': {
          backgroundColor: theme('colors.matched.light'),
          color: theme('colors.matched.DEFAULT'),
        },
        '.status-exception': {
          backgroundColor: theme('colors.exception.light'),
          color: theme('colors.exception.DEFAULT'),
        },
        '.status-pending': {
          backgroundColor: theme('colors.pending.light'),
          color: theme('colors.pending.foreground'),
        },
        '.status-processing': {
          backgroundColor: theme('colors.processing.light'),
          color: theme('colors.processing.DEFAULT'),
        },
      });
    },
  ],
}