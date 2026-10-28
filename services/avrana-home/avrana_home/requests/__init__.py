"""The request broker: asking an upstream request service for something on the member's behalf.

Home's first write path. Everything here is separate from `adapters/` (which stay GET-only and read the member's
own libraries): a request client talks to ONE request service, through its own allow-list, with a credential that
never reaches the browser, and acts for the verified principal only (never for an id or username from the request).
See docs/design/UNIVERSAL-SEARCH-AND-REQUESTS.md.
"""
