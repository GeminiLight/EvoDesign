import type { Adapter } from '../parity/functions.test.ts';
import { _MembershipContext } from '../../src/verification_stage/checks/containment.ts';

// ``context`` is a frozen dataclass recorded as its fields; ``use_explicit`` is
// a property, so rebuild the instance before the call.
export default {
  _resolve_parent_group: {
    args: (bound) => [bound[0], bound[1], new _MembershipContext(bound[2] as ConstructorParameters<typeof _MembershipContext>[0])],
  },
} satisfies Record<string, Adapter>;
