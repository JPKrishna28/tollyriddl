/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark cinematic base with a warm gold accent -- film-marquee
        // colouring rather than a dashboard palette.
        ink: {
          950: '#080a12',
          900: '#0d1020',
          850: '#12162a',
          800: '#171c33',
          700: '#222842',
          600: '#2f3757',
        },
        gold: {
          400: '#f5c451',
          500: '#e6a92c',
          600: '#c98d16',
        },
        match: {
          400: '#34d399',
          500: '#10b981',
          600: '#059669',
        },
        miss: {
          500: '#64748b',
        },
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', 'Georgia', 'serif'],
        // Noto Sans Telugu keeps Telugu-script titles legible.
        sans: [
          'Inter',
          'system-ui',
          '"Noto Sans Telugu"',
          '"Noto Sans"',
          'sans-serif',
        ],
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'pop-in': {
          '0%': { opacity: '0', transform: 'scale(0.94)' },
          '60%': { transform: 'scale(1.02)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'flip-in': {
          '0%': { opacity: '0', transform: 'rotateX(-70deg)' },
          '100%': { opacity: '1', transform: 'rotateX(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 320ms ease-out both',
        'pop-in': 'pop-in 260ms ease-out both',
        'flip-in': 'flip-in 380ms ease-out both',
      },
    },
  },
  plugins: [],
};
