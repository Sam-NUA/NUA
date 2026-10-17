module.exports = {
  testEnvironment: 'jsdom',
  roots: ['<rootDir>/src'],
  transform: { '^.+\\.[jt]sx?$': ['babel-jest', { presets: [
    ['@babel/preset-env', { targets: { node: 'current' } }],
    ['@babel/preset-react', { runtime: 'automatic' }],
  ] }] },
  moduleNameMapper: { '^@/(.*)$': '<rootDir>/src/$1' },
};
