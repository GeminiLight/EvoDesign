## Er Diagram

### Common
- Best for database entity relationships and data models.
- Identity signal: entity rectangles connected through relationship diamonds and cardinality labels.
- CRITICAL: ER diagrams must be COMPREHENSIVE. Extract every entity, every attribute, every relationship. Missing elements breaks the data model. When in doubt, INCLUDE the entity — do not drop it.
- CHEN NOTATION MANDATORY: entities as rectangles, attributes as ellipses, relationships as DIAMONDS. A relationship like 'Customer initiates Deposit' must create a diamond node labeled 'initiates' connected to both Customer and Deposit. Do NOT use edge labels for relationships.

#### Visual Pattern: ER Notation
Chen notation — every relationship is a diamond node, NOT an edge label:

```
  ┌─────────┐              ┌──────────┐
  │Customer │              │  Order   │
  ├─────────┤              ├──────────┤
  │ id (PK) │              │ id  (PK) │
  │ name    │              │ total    │
  └────┬────┘              └────┬─────┘
       │                        │
       │      ┌──────────┐      │
       └─────►│ places   │◄─────┘
         1    │  1:N     │    N
                └──────────┘
```

#### Cardinality Notation
Use text labels or crow's foot:
- `1` - One
- `N` or `*` - Many
- `0..1` - Zero or one
- `1..*` - One or more

### Structure
- ER diagrams are DATA MODELS — aim for COMPLETENESS, not minimalism. Extract ALL entities, attributes, and relationships the source text describes. Unlike process diagrams, missing an entity or relationship in an ER diagram breaks the data model's integrity.
- Use three distinct node classes: 'entity' (rectangles), 'attribute' (ellipses), and 'relationship' (diamonds). Every relationship verb (initiates, routes, owns, etc.) MUST be a separate diamond node, NOT an edge label.
- Relationship nodes connect to entities via edges. For 'Customer initiates Deposit', create: entity_customer -> rel_initiates -> entity_deposit. The edge label carries cardinality (1:N, M:N).
- Primary keys should be explicitly distinguishable from regular attributes using class 'primary_key'.
- Every entity mentioned or implied by the source text must appear as a node. Do NOT skip 'minor' entities — in a data model, every entity matters.
- Every relationship between entities that the source text describes must appear as a diamond node with two edges (one to each participating entity). Do NOT omit relationships just because they seem obvious from context.
- Attributes mentioned in the source text (name, address, balance, etc.) should be extracted as attribute nodes connected to their parent entity via 'has' edges. More attributes = more informative diagram.
- [Budget] ALL entities + ALL relationship diamonds in the source text (aim for completeness); 0 groups; edges connect entities↔relationships and entities↔attributes
- [Edge Rules] Two edges per relationship (entity→diamond→entity). One edge per attribute (entity→attribute). Cardinality labels on relationship edges. NO redundant inverse edges.

### Styling
- Use rectangles for entities, ellipses for attributes, and diamonds for relationships.
- Apply a distinct fill color to primary key nodes (e.g., light yellow or light green).
- Relationship diamonds should use a contrasting fill (e.g., light orange) to stand out from entities.
- Edge labels show cardinality (1:N, M:N) near the entity end of the edge.

### Layout
- [Detailed Layout Instructions]
  - `chart_type=="er_diagram"` → follow the ER layout rules in your stage knowledge (midpoint diamonds, cluster grouping, attribute star pattern).
- POSITIONING RULE: For each relationship diamond connecting entity A and entity B, compute the midpoint: diamond.x = (A.x + B.x) / 2, diamond.y = (A.y + B.y) / 2. This guarantees short, non-crossing edges.
- CLUSTER RULE: Group entities by their relationships. If Customer initiates Deposit, Withdrawal, Loan — place Customer on one side, the three transaction entities on the other, with relationship diamonds in between.
- ATTRIBUTE RULE: Place attributes in a tight star around their parent entity. Attribute center should be 80-120px from entity center. Place primary keys directly below entity, other attributes to left/right/above.
- EDGE CROSSING MINIMIZATION: If an entity participates in multiple relationships with entities on the same side, stagger the relationship diamonds vertically (100-150px apart) so edges don't overlap.
- COMPACTNESS: Keep total diagram width under 2000px. Use 200-300px horizontal spacing between entity clusters. Attributes should not extend beyond the entity cluster boundary.
- [Geometry] Cluster pattern: relationship diamond centered between its two entities. Attributes in star pattern around parent entity. Grid spacing 200-300px.
