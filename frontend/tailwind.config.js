/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['Vazirmatn', 'Tahoma', 'sans-serif'] },
      colors: {
        paper: '#fcfcfa', ink: '#202936', muted: '#5c6775', rule: '#dce1e6', wash: '#f3f4f4',
      },
      fontSize: {
        xs: ['0.75rem', { lineHeight: '1.85' }],
        sm: ['0.875rem', { lineHeight: '1.85' }],
        base: ['1rem', { lineHeight: '1.9' }],
        lg: ['1.125rem', { lineHeight: '1.8' }],
        xl: ['1.25rem', { lineHeight: '1.8' }],
        '2xl': ['1.5rem', { lineHeight: '1.7' }],
        '3xl': ['1.875rem', { lineHeight: '1.65' }],
        display: ['2rem', { lineHeight: '1.65', fontWeight: '600' }],
        heading: ['1.25rem', { lineHeight: '1.8', fontWeight: '600' }],
        body: ['0.9375rem', { lineHeight: '2' }],
        caption: ['0.75rem', { lineHeight: '1.85' }],
      },
    },
  },
  plugins: [],
};
