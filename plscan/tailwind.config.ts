import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: '#0D0D1A',
          secondary: '#13132A',
          tertiary: '#1A1A35'
        },
        accent: {
          primary: '#8A2BE2',
          secondary: '#B44FFF',
          tertiary: '#FF2D9D'
        },
        text: {
          primary: '#FFFFFF',
          secondary: '#A0A0C0',
          tertiary: '#5A5A80'
        },
        buy: '#00E5A0',
        sell: '#FF4D6D',
        border: 'rgba(138, 43, 226, 0.2)'
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-jetbrains)', 'monospace']
      },
      boxShadow: {
        glow: '0 0 12px rgba(138, 43, 226, 0.3)',
        'glow-strong': '0 0 24px rgba(138, 43, 226, 0.5)'
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(135deg, #8A2BE2, #FF2D9D)'
      }
    }
  },
  plugins: []
};
export default config;
