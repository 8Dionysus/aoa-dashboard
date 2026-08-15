# Technology choice

The first slice uses Python's standard-library `http.server`, `unittest`, and
vanilla HTML/CSS/JavaScript. This is a deliberate bounded choice, not a
generic web template:

- neighboring owner services and MCP surfaces are predominantly Python;
- existing adjacent UI evidence includes a larger Vite/TypeScript graph
  workbench, but no shared Goal Space frontend package was found;
- a read-mostly host-local slice does not need a framework, package lock, or
  new deployment dependency yet;
- standard-library code keeps the adapter boundary visible and makes the
  source/missingness tests runnable in the empty repository.

The choice can be revisited when the owner contracts and action plane have a
real integration pressure. It is not evidence that a production deployment
should remain framework-free.
