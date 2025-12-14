/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ["./web/**/*.{html,js}"],
    theme: {
        extend: {
            colors: {
                'bg': '#000000',
                'surface': '#0a0a0a',
                'surface-hover': '#1a1a1a',
                'border': '#2a2a2a',
                'border-light': '#3a3a3a',
                'text-primary': '#ffffff',
                'text-secondary': '#888888',
                'text-muted': '#555555',
                'particle-a': 'hsl(0, 100%, 50%)',
                'particle-b': 'hsl(220, 100%, 50%)',
            },
            spacing: {
                'xs': '4px',
                'sm': '8px',
                'md': '16px',
                'lg': '24px',
                'xl': '32px',
            },
            borderRadius: {
                'panel': '12px',
            },
            fontFamily: {
                'sans': ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
            },
            fontSize: {
                'xs': '10px',
                'sm': '12px',
                'md': '14px',
                'lg': '16px',
                'xl': '18px',
            },
            maxWidth: {
                'app': '1600px',
            },
            gridTemplateColumns: {
                'app': '1.3fr 1fr',
                'top-row': '1.5fr 1fr',
                'slider-pair': '1fr 1fr',
            },
        },
    },
    plugins: [],
}
