// Ported from evodesign/agentic_system/config.py — keep in sync.
//
// The ``@dataclass AgenticSystemConfig`` becomes a class whose constructor
// takes one object of field values (``AgenticSystemConfig(**kwargs)``);
// fields keep the Python names and defaults, ``__post_init__`` runs at the
// end of the constructor.

import { ValueError, RuntimeError } from '../py/errors.ts';
import { getLogger } from '../py/logging.ts';
import { pyRepr } from '../py/str.ts';
import { normalize_canvas_library } from '../canvas_runtime.ts';
import { AppSettings, normalize_generation_mode } from '../config/settings.ts';
import { canonical_method_name } from '../core/experiment.ts';

const logger = getLogger('evodesign.agentic_system.config');

// ``canvas_environment.capabilities`` is ported by WP14, which builds on this
// work package; it is loaded lazily so this module works before it exists.
interface CapabilitiesModule {
  require_generation_capability: (canvas_library: string, mode: string) => void;
  require_refiner_capability: (canvas_library: string, mode: string) => void;
}
const CAPABILITIES_PATH = '../canvas_environment/capabilities.ts';
const capabilities = (await import('../canvas_environment/capabilities.ts').catch(() => null)) as CapabilitiesModule | null;

function require_generation_capability(canvas_library: string, mode: string): void {
  if (!capabilities) throw new RuntimeError('canvas_environment/capabilities.ts is not ported yet (WP14)');
  capabilities.require_generation_capability(canvas_library, mode);
}

function require_refiner_capability(canvas_library: string, mode: string): void {
  if (!capabilities) throw new RuntimeError('canvas_environment/capabilities.ts is not ported yet (WP14)');
  capabilities.require_refiner_capability(canvas_library, mode);
}

// Variant → default configuration mapping.
// When a user selects a variant, these values act as the baseline config.
// Any explicitly-provided CLI argument overrides the preset.
export const _VARIANT_PRESETS: Record<string, { enable_refiner: boolean; mode: string; use_icons: boolean }> = {
  evodesign: {
    enable_refiner: true,
    mode: 'multiagent',
    use_icons: true,
  },
  evodesign_wo_refiner: {
    enable_refiner: false,
    mode: 'multiagent',
    use_icons: true,
  },
  evodesign_wo_multiagent: {
    enable_refiner: false,
    mode: 'oneshot',
    use_icons: true,
  },
  evodesign_wo_icons: {
    enable_refiner: true,
    mode: 'multiagent',
    use_icons: false,
  },
};

/** Return the supported experiment variant names. */
export function list_variant_presets(): string[] {
  return Object.keys(_VARIANT_PRESETS).sort();
}

/** Return the preset defaults for a given variant. */
export function get_variant_preset(variant: string): Record<string, unknown> {
  variant = canonical_method_name(variant);
  if (!Object.prototype.hasOwnProperty.call(_VARIANT_PRESETS, variant)) {
    const supported = list_variant_presets().join(', ');
    throw new ValueError(`Unknown variant: ${pyRepr(variant)}. Use one of: ${supported}.`);
  }
  return { ..._VARIANT_PRESETS[variant] };
}

export type AgenticSystemConfigFields = Partial<Omit<AgenticSystemConfig, 'toJSON'>>;

export class AgenticSystemConfig {
  // ── Provider (pass-through from CLI) ─────────────────────────────────
  role = 'generator'; // Role in models.yaml
  model_override: string | null = null; // --model alias override

  // ── Generation strategy ──────────────────────────────────────────────
  mode = 'multiagent'; // "multiagent" (Structure→Styling→Layout) or "oneshot" (single LLM call)
  save_intermediate = true; // False to disable saving intermediate JSON/PNG
  tag: string | null = null; // Tag appended to output dir to avoid overwriting
  variant = 'evodesign'; // Experiment variant: evodesign, evodesign_wo_refiner, etc.

  // ── Tool toggles ────────────────────────────────────────────────────
  use_icons = false; // add Material Design icons to diagram nodes
  canvas_library = 'excalidraw'; // "excalidraw" or "tldraw"
  full_domain_knowledge = true; // inject all stage rules into every agent

  // ── Refiner ──────────────────────────────────────────────────────────
  enable_refiner = false;
  refiner_iterations = 3;

  // ── Verification ─────────────────────────────────────────────────────
  enable_verifier = true;
  verification_only = false;
  enable_critic = true;

  // ── User Memory ──────────────────────────────────────────────────────
  enable_user_memory = false;
  user_id = 'default_user';
  session_id: string | null = null;
  memory_db_path: string | null = null; // resolved from AppSettings in __post_init__

  // ── Design Memory ────────────────────────────────────────────────────
  // Evolved design knowledge retrieved at generation time. On by default
  // because it is part of the system under evaluation; every failure path
  // degrades to "generate without design knowledge".
  enable_design_memory = true;
  design_memory_db_path: string | null = null; // resolved from AppSettings in __post_init__
  design_memory_embedding_model: string | null = null; // None → settings.yaml
  design_memory_top_k = 5;
  design_memory_score_threshold = 0.0;

  // ── Learn-from-edit mode ─────────────────────────────────────────────
  learn_from_edit = false;
  task_json: string | null = null;
  model_manifest: string | null = null;
  model_image: string | null = null;
  user_manifest: string | null = null;
  user_image: string | null = null;

  constructor(fields: AgenticSystemConfigFields = {}) {
    for (const [key, value] of Object.entries(fields)) {
      if (!(key in this)) throw new TypeError(`AgenticSystemConfig.__init__() got an unexpected keyword argument '${key}'`);
      if (value !== undefined) (this as Record<string, unknown>)[key] = value;
    }
    this.__post_init__();
  }

  __post_init__(): void {
    this.mode = normalize_generation_mode(this.mode);

    this.canvas_library = normalize_canvas_library(this.canvas_library);
    require_generation_capability(this.canvas_library, this.mode);

    if (this.enable_refiner) {
      require_refiner_capability(this.canvas_library, this.mode);
    }

    // Only resolve implicit defaults here. Programmatic values passed to
    // AgenticSystemConfig must remain authoritative for reproducible runs.
    try {
      if (this.memory_db_path === null) {
        this.memory_db_path = AppSettings.get_default().user_preference_memory_path;
      }
    } catch (exc) {
      if (this.enable_user_memory) {
        throw new RuntimeError(
          'Could not resolve user preference memory path from settings. '
          + 'Pass memory_db_path explicitly or fix settings.yaml before '
          + 'enabling user memory.',
        );
      }
      logger.warning(
        'Could not resolve default user preference memory path; '
        + 'continuing with memory_db_path=None because user memory is disabled: %s',
        exc,
      );
    }

    // Design memory deliberately does NOT mirror the user-memory branch
    // above: it never raises.
    try {
      if (this.design_memory_db_path === null) {
        this.design_memory_db_path = AppSettings.get_default().design_memory_vector_db_path;
      }
    } catch (exc) {
      logger.warning(
        'Could not resolve default design memory vector store path; '
        + 'design memory will be skipped unless design_memory_db_path is '
        + 'passed explicitly: %s',
        exc,
      );
    }
  }
}
