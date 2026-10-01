// Combined Allure report for both suites (Story 1.6). One self-contained
// index.html, so the report opens from a downloaded artifact without a server.
export default {
  name: 'PoolBrain QA',
  plugins: {
    awesome: {
      options: { singleFile: true, reportLanguage: 'en' },
    },
  },
};
