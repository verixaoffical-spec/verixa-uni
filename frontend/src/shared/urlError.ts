// Anyone can put text in ?error= and send the link to someone, so only messages the server really sends are shown.
const KNOWN = ['GitHub sign in was cancelled', 'Atlassian sign in was cancelled', 'Sign in expired. Please try again',
  'Log in first', 'No Jira site found on this Atlassian account'];
const ALREADY_LINKED = /^GitHub account [\w-]{1,39} is already linked to another Verixa account$/;

export const urlError = (message: string) =>
  KNOWN.includes(message) || ALREADY_LINKED.test(message) ? message : 'Sign in could not be completed. Please try again.';
