## Class Diagram

### Common
- Best for class structures and inheritance relationships.
- Identity signal: compartmentalized class boxes with typed UML connectors.

#### Visual Pattern
Three-compartment boxes with typed connectors:

```
       ┌──────────────┐
       │   <<User>>   │
       ├──────────────┤
       │ - name       │
       │ - email      │
       ├──────────────┤
       │ + login()    │
       └──────┬───────┘
              △
              │ inherits
              │
       ┌──────┴───────┐          ┌──────────────┐
       │   Customer   │◄─────────│    Order     │
       ├──────────────┤  places  ├──────────────┤
       │ - address    │    1:N   │ - id         │
       │ - vip        │          │ - total      │
       ├──────────────┤          ├──────────────┤
       │ + checkout() │          │ + cancel()   │
       └──────────────┘          └──────┬───────┘
                                        │
                                        ◇ composes
                                        │
                                   ┌────┴────┐
                                   │OrderItem│
                                   └─────────┘
```

### Structure
- Class diagrams are DATA MODELS — aim for COMPLETENESS, not minimalism. Extract ALL classes the source text mentions. Missing a class breaks the model's integrity.
- Use class nodes with three compartments: class name, attributes, and methods.
- Differentiate relationship semantics such as inheritance, association, aggregation, and composition.
- Parent classes should remain structurally distinguishable from subclasses.
- [Budget] ALL entities/classes in the source text (aim for completeness); 0 groups; relationship per association, NO redundant inverse edges
- [Edge Rules] Expected count: one per association. Labels carry cardinality or relation verb. NO redundant inverse edges.

### Styling
- Use rectangles divided into three sections for each class.
- Use hollow triangle arrows for inheritance, standard arrows for association, and diamond-ended arrows for aggregation/composition.
- Allocate visual room for multi-line attributes and methods.

### Layout
- Primary family: Layered / Hierarchical.
- Place parent classes above subclasses.
- Arrange related peer classes horizontally where possible.
- Keep relationship edges legible around the class compartments.
- [Geometry] Top-to-bottom layered layout. Classes at top level. Inheritance flows downward. Association edges connect peers.
