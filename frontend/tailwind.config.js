/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['Vazirmatn', 'Tahoma', 'sans-serif'] },
      colors: {
        paper: 'rgb(var(--paper) / <alpha-value>)', ink: 'rgb(var(--ink) / <alpha-value>)', muted: 'rgb(var(--muted) / <alpha-value>)', rule: 'rgb(var(--rule) / <alpha-value>)', wash: 'rgb(var(--wash) / <alpha-value>)',
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
