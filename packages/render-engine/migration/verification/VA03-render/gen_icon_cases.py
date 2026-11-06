import json
from pathlib import Path
from evodesign.agentic_system.common.node_icons import bundled_icons,icon_file
out=Path(__file__).resolve().parent
cases=[{'name':name,'color':color,'result':icon_file(name,color)} for name in bundled_icons() for color in ('#123456','#FFFFFF','bad_color')]
(out/'icons-python.json').write_text(json.dumps(cases,ensure_ascii=False,indent=1)+'\n')
print(len(bundled_icons()),'icons;',len(cases),'cases')
