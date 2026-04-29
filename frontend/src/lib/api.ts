/** Typed API client for the Unstructured Mapping FastAPI backend. */

export type EntityType =
	| 'person'
	| 'organization'
	| 'place'
	| 'topic'
	| 'product'
	| 'legislation'
	| 'asset'
	| 'metric'
	| 'role'
	| 'relation_kind';

export type EntityStatus = 'active' | 'merged' | 'deprecated';
export type RunStatus = 'running' | 'completed' | 'failed';

export interface Entity {
	entity_id: string;
	canonical_name: string;
	entity_type: EntityType;
	subtype: string | null;
	description: string;
	aliases: string[];
	status: EntityStatus;
	valid_from: string | null;
	valid_until: string | null;
	created_at: string | null;
	updated_at: string | null;
	merged_into: string | null;
	relationship_count?: number;
	mention_count?: number;
}

export interface Relationship {
	source_id: string;
	target_id: string;
	relation_type: string;
	description: string;
	qualifier_id: string | null;
	relation_kind_id: string | null;
	valid_from: string | null;
	valid_until: string | null;
	document_id: string | null;
	discovered_at: string | null;
	run_id: string | null;
	confidence: number | null;
}

export interface Provenance {
	entity_id: string;
	document_id: string;
	source: string;
	mention_text: string;
	context_snippet: string;
	detected_at: string | null;
	run_id: string | null;
}

export interface RunMetrics {
	run_id: string;
	chunks_processed: number;
	mentions_detected: number;
	mentions_resolved_alias: number;
	mentions_resolved_llm: number;
	llm_resolver_calls: number;
	llm_extractor_calls: number;
	proposals_saved: number;
	relationships_saved: number;
	provider_name: string | null;
	model_name: string | null;
	wall_clock_seconds: number;
	input_tokens: number;
	output_tokens: number;
}

export interface Run {
	run_id: string;
	status: RunStatus;
	started_at: string;
	finished_at: string | null;
	document_count: number;
	entity_count: number;
	relationship_count: number;
	error_message: string | null;
	metrics: RunMetrics | null;
}

export interface Article {
	document_id: string;
	url: string;
	title: string;
	body: string;
	source: string;
	published: string | null;
}

export interface HealthResponse {
	entities: { total: number; by_type: Record<string, number> };
	relationships: number;
	articles: { total: number; by_source: Record<string, number> };
	latest_run: Run | null;
}

export interface PopulateStage {
	name: string;
	created: number;
	skipped: number;
}

export interface PopulateResponse {
	stages: PopulateStage[];
	total_created: number;
	total_skipped: number;
}

export interface WikidataRefreshType {
	type: string;
	fetched: number;
	created: number;
	skipped: number;
	error: string | null;
}

export interface WikidataRefreshResponse {
	types: WikidataRefreshType[];
	total_created: number;
	total_skipped: number;
}

export interface AliasEntity {
	entity_id: string;
	canonical_name: string;
	entity_type: string;
	mention_count: number;
	is_merge_target: boolean;
}

export interface AliasCollision {
	alias: string;
	total_mentions: number;
	same_type: boolean;
	entities: AliasEntity[];
}

export interface AliasAuditResponse {
	total: number;
	collisions: AliasCollision[];
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
	const url = new URL(path, window.location.origin);
	if (params) {
		for (const [k, v] of Object.entries(params)) {
			if (v !== undefined) url.searchParams.set(k, String(v));
		}
	}
	const res = await fetch(url.toString());
	if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
	return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
	const res = await fetch(path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
	return res.json();
}

export const api = {
	health: () => get<HealthResponse>('/api/health'),

	entities: {
		list: (params?: { q?: string; type?: string; status?: string; limit?: number; offset?: number }) =>
			get<Entity[]>('/api/entities', params),
		get: (id: string) => get<Entity>(`/api/entities/${id}`),
		relationships: (id: string) => get<Relationship[]>(`/api/entities/${id}/relationships`),
		provenance: (id: string) => get<Provenance[]>(`/api/entities/${id}/provenance`)
	},

	relationships: {
		list: (params: {
			entity_id?: string;
			source_id?: string;
			target_id?: string;
			type?: string;
			min_confidence?: number;
		}) => get<Relationship[]>('/api/relationships', params)
	},

	runs: {
		list: (limit?: number) => get<Run[]>('/api/runs', { limit }),
		get: (id: string) => get<Run>(`/api/runs/${id}`),
		ingest: (params?: {
			provider?: string;
			model?: string;
			limit?: number;
			cold_start?: boolean;
			extract_relationships?: boolean;
			source?: string;
		}) => post<{ status: string; message: string }>('/api/runs/ingest', params ?? {}),
		stream: (id: string) => new EventSource(`/api/runs/${id}/stream`)
	},

	scrape: {
		trigger: (sources?: string[]) =>
			post<{ status: string; sources: string[]; message: string }>('/api/scrape', {
				sources: sources ?? ['bbc', 'reuters', 'ap']
			}),
		articles: (params?: { source?: string; limit?: number; offset?: number }) =>
			get<Article[]>('/api/scrape/articles', params)
	},

	kg: {
		populate: () => post<PopulateResponse>('/api/kg/populate', {}),
		wikidataRefresh: (types?: string[], limit?: number) =>
			post<WikidataRefreshResponse>('/api/kg/wikidata-refresh', {
				types: types ?? null,
				limit: limit ?? 100
			}),
		aliasAudit: (minMentions?: number) =>
			get<AliasAuditResponse>('/api/kg/alias-audit', {
				min_mentions: minMentions ?? 0
			})
	}
};
