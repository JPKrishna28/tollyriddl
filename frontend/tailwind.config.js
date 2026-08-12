/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // White surface, muted ink accents. Green/red are desaturated so a
        // correct/incorrect verdict reads clearly without glowing.
        accent: {
          50: '#f8fafc',
          200: '#e2e8f0',
          500: '#475569',
          700: '#334155',
        },
        // Armed-lifeline highlight. Warm on purpose: the rest of the palette
        // is slate/green/red, so an amber ring reads as "pick one of these"
        // without colliding with a match or a miss.
        arm: {
          50: '#fdf6e7',
          200: '#f5dfa6',
          400: '#e0a72e',
          500: '#c98f1c',
          600: '#a87415',
          700: '#7d5610',
        },
        match: {
          50: '#f0f7f2',
          200: '#c9e2d2',
          500: '#4e8f68',
          600: '#3f7455',
          700: '#336046',
        },
        miss: {
          50: '#fdf3f3',
          200: '#f0cfcf',
          500: '#b4544f',
          600: '#9a4541',
          700: '#7d3835',
        },
        // Crew attributes (director / production / music / writer) read as a
        // third group. Muted indigo to match the red and green in weight.
        crew: {
          50: '#f2f3f9',
          200: '#cdd0e6',
          500: '#5b6091',
          600: '#4b4f79',
          700: '#3c3f61',
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
