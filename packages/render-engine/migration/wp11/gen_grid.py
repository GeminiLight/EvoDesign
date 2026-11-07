import json, sys, random
from evodesign.agentic_system.render_engine.excalidraw.arrow_routing import grid_router as g
random.seed(11)
cases = []
for i in range(400):
    n = random.randint(0, 7)
    step = random.choice([10, 20, 25])
    obstacles = []
    for _ in range(n):
        obstacles.append((float(random.randint(0, 20) * step), float(random.randint(0, 20) * step), float(random.randint(2, 6) * step), float(random.randint(2, 5) * step)))
    def pt(): return (float(random.randint(-2, 24) * step), float(random.randint(-2, 24) * step))
    start, end = pt(), pt()
    if random.random() < 0.3: end = (start[0], end[1])
    if random.random() < 0.2: start = (-0.0, start[1])
    arrows = []
    for _ in range(random.randint(0, 3)):
        x, y = pt()
        pts = [[0.0, 0.0]]
        for _ in range(random.randint(1, 3)):
            if random.random() < .5: pts.append([pts[-1][0] + random.randint(-8, 8) * step, pts[-1][1]])
            else: pts.append([pts[-1][0], pts[-1][1] + random.randint(-8, 8) * step])
        arrows.append({"type": "arrow", "x": x, "y": y, "points": pts, "isDeleted": random.random() < .1, "opacity": random.choice([100, 0, 50])})
    clearance = random.choice([0.0, 8.0, 12.5, 20.0])
    normals = random.choice([None, ((1.0, 0.0), (-1.0, 0.0)), ((0.0, 1.0), (0.0, -1.0)), ((0.0, -1.0), (1.0, 0.0))])
    r = g._find_orthogonal_visibility_route(start, end, obstacles, arrows, clearance, normals)
    key = g._route_memo_key(start, end, obstacles, arrows, clearance, normals)
    cases.append({"args": [start, end, obstacles, arrows, clearance, normals], "result": r, "key": key})
json.dump(cases, open(sys.argv[1], "w"))
print(len(cases), sum(c["result"] is not None for c in cases))
