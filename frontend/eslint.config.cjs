const globals = require('globals');
const react = require('eslint-plugin-react');
module.exports = [
  { ignores: ['build/**', 'node_modules/**'] },
  { files: ['src/**/*.{js,jsx}'],
    languageOptions: { ecmaVersion: 'latest', sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } }, globals: { ...globals.browser, process: 'readonly' } },
    plugins: { react },
    rules: { 'no-undef': 'error', 'react/jsx-no-undef': 'error' },
  },
  { files: ['src/**/__tests__/**'], languageOptions: { globals: { ...globals.jest, ...globals.node } } },
];
