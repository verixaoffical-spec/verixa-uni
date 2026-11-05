import { test, expect } from '@playwright/test';

// Accepted on purpose: the title is only text. It must show as text, and no alert may appear.
test('<img src=x onerror=alert(1)>', async () => {
  expect(1).toBe(1);
});
