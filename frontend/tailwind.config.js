const plugin = require('tailwindcss/plugin');

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Aptos', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '\"Segoe UI\"', 'sans-serif'],
        display: ['\"Avenir Next\"', 'Aptos', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      // `4.5` (18px) is used ~45 times for icon sizing. Tailwind v3 has no 4.5 key
      // by default, so every `h-4.5`/`w-4.5` silently emitted no CSS and the icons
      // fell back to lucide's intrinsic 24px. Defining it restores the intended size.
      spacing: {
        '4.5': '1.125rem',
      },
      // Tailwind v3 ships opacity in steps of 5, so modifiers like
      // `dark:bg-slate-900/78` matched nothing and were dropped silently — which
      // is why several dark-mode surfaces kept rendering their light background.
      // Around 100 usages across the app sat on off-scale values; allowing every
      // integer fixes them all at once and stops the failure mode recurring.
      // Only classes actually used are emitted, so this costs nothing in output.
      opacity: Object.fromEntries(
        Array.from({ length: 101 }, (_, i) => [String(i), String(i / 100)]),
      ),
      colors: {
        brand: {
          50: '#f2fbff',
          100: '#d8f1ff',
          200: '#b4e1ff',
          300: '#84cbff',
          400: '#52aeff',
          500: '#318dff',
          600: '#1e6ef5',
          700: '#1756d1',
          800: '#1a49a5',
          900: '#1a3f81',
          950: '#10264d',
        },
        canvas: '#f5fbff',
      },
      // Named elevation scale. Replaces one-off `shadow-[0_24px_70px_rgba(...)]`
      // values so surfaces at the same depth cast the same shadow.
      boxShadow: {
        glass: '0 25px 70px rgba(15, 23, 42, 0.12)',
        'e1': '0 1px 2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04)',
        'e2': '0 4px 12px -2px rgba(15, 23, 42, 0.08), 0 2px 6px -2px rgba(15, 23, 42, 0.05)',
        'e3': '0 12px 28px -8px rgba(15, 23, 42, 0.12), 0 4px 10px -4px rgba(15, 23, 42, 0.06)',
        'e4': '0 24px 56px -16px rgba(15, 23, 42, 0.18), 0 8px 20px -8px rgba(15, 23, 42, 0.08)',
        'e5': '0 40px 90px -24px rgba(15, 23, 42, 0.26), 0 12px 28px -12px rgba(15, 23, 42, 0.10)',
        'e1-dark': '0 1px 2px rgba(0, 0, 0, 0.4)',
        'e2-dark': '0 4px 12px -2px rgba(0, 0, 0, 0.45)',
        'e3-dark': '0 12px 28px -8px rgba(0, 0, 0, 0.55)',
        'e4-dark': '0 24px 56px -16px rgba(0, 0, 0, 0.6)',
        'e5-dark': '0 40px 90px -24px rgba(0, 0, 0, 0.7)',
      },
      backgroundImage: {
        'grid-light':
          'linear-gradient(rgba(99, 179, 237, 0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(99, 179, 237, 0.15) 1px, transparent 1px)',
        'radial-fade':
          'radial-gradient(circle at top, rgba(82, 174, 255, 0.16), transparent 56%)',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    plugin(({ addVariant }) => {
      // Pointer-aware variants. A 44px control is right for a finger and too
      // heavy for a mouse; these let dense desktop clusters stay compact while
      // keeping full-size targets on touch devices.
      addVariant('touch', '@media (pointer: coarse)');
      addVariant('fine', '@media (pointer: fine)');
    }),
  ],
}
