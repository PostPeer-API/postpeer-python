/** @type {import('@hey-api/openapi-python').UserConfig} */
export default {
  input: './openapi.json',
  output: {
    path: './src/postpeer/_generated',
  },
  plugins: ['pydantic'],
};
