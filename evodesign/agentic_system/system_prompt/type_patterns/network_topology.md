## Network Topology

### Common
- Best for network structures and node connections.
- Identity signal: connected devices arranged as a non-linear topology.

#### Visual Pattern
```
              ┌─────────┐
              │Internet │
              └────┬────┘
                   │
              ┌────┴────┐
              │Firewall │
              └────┬────┘
         ┌─────────┼─────────┐
    ┌────┴────┐ ┌──┴───┐ ┌───┴───┐
    │   Web   │ │ App  │ │  DB   │
    └─────────┘ └──────┘ └───────┘
```

### Structure
- Use node roles for different device or component types and allow many-to-many connectivity.
- Connections may encode link importance or bandwidth.
- Network readability depends on controlling clutter in dense connectivity patterns.
- [Budget] components; one group per layer/zone (2-5); ONLY named data/control flows, layer membership implies the rest
- [Edge Rules] Expected count: only named flows (usually ≤ n/2). Labels carry protocol or flow name.

### Styling
- Use different shapes for different device types, such as rectangles, ellipses, or diamonds.
- Differentiate device importance through color and size.
- Use line width to represent bandwidth when that data is present.

### Layout
- Primary family: Network.
- Place core devices near the center and group other devices by hierarchy or function.
- Optimize the spatial arrangement for readable many-to-many connections.
- Prevent visual clutter from overwhelming the topology.
- [Geometry] Layered or mesh layout. Nodes represent network devices/services. Group by zone or subnet. Named connection flows only.
