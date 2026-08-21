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

## Native desktop shell

The desktop slice is a thin application shell around the existing web
surface. GTK4 and Libadwaita own the application and window lifecycle;
WebKitGTK 6.0 renders the checked-in `web/` HTML/CSS/JavaScript directly. No
Electron, Tauri, Node runtime, second frontend, or native widget rewrite is
introduced.

The shell creates the existing standard-library HTTP server on loopback with
port `0`, allowing the operating system to select the port. The application
passes the resulting URL to WebKit and shuts the server down during
application shutdown. GTK, Libadwaita, WebKitGTK, and PyGObject remain host
runtime requirements; the package does not silently vendor system libraries.
