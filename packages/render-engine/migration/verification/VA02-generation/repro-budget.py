"""Original Python ContextVar / ThreadPoolExecutor control for repro-budget.ts."""
import json
import threading
from pathlib import Path
from langchain_core.messages import AIMessage
import evodesign.core.base_agent as base
from evodesign.agentic_system.common.self_consistency import sample_and_vote
from evodesign.agentic_system.generation_stage.structure.structure_agent import _unwrap_and_validate_structure_sample
class ProbeAgent(base.BaseAgent):
 def run(self,state):return state
first=threading.Barrier(3)
second=threading.Barrier(3)
lock=threading.Lock()
next_sample=0
attempts=[0,0,0]
events=[]
class Model:
 def invoke(self,messages):
  sample=int(messages[0].content)
  with lock:
   attempts[sample]+=1
   attempt=attempts[sample]
   events.append({'sample':sample,'attempt':attempt,'budget_retries':base._CALL_BUDGET.get().retries_left})
  if attempt==1:
   first.wait(timeout=5)
   return AIMessage(content='malformed JSON')
  if attempt==2:
   second.wait(timeout=5)
   raise base.LLMResponseError('malformed provider response')
  return AIMessage(content=json.dumps({'specification':{'sample':sample},'instantiation':{'chart_type':'flowchart' if sample==0 else 'architecture','nodes':[{'id':'a','label':'A','class':'step'}],'edges':[],'groups':[]}}))
base._sleep=lambda seconds:None
agent=object.__new__(ProbeAgent)
agent._tools=[]
agent._model=Model()
agent.jsonalize_output=True
agent.strict_json_output=True
agent.json_retry_attempts=2
agent.exclude_think=True
agent.transport_attempts=2
agent.call_deadline_seconds=0
def invoke(_):
 global next_sample
 with lock:
  sample=next_sample
  next_sample+=1
 return agent.invoke_with_history([{'role':'user','content':str(sample)}])
result=sample_and_vote(invoke,{},n_samples=3,vote_key='chart_type',unwrap_fn=_unwrap_and_validate_structure_sample)
output={'mode':'python','attempts':attempts,'total_model_requests':sum(attempts),'winner':result,'events':events}
Path(__file__).with_name('budget-python.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output))
