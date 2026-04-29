<script lang="ts">
	import { SvelteFlow, Background, Controls, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { api, type Entity, type Relationship } from '$lib/api';

	const TYPE_COLORS: Record<string, string> = {
		person: '#4299e1',
		organization: '#48bb78',
		place: '#ed8936',
		topic: '#9f7aea',
		asset: '#fc8181',
		product: '#f6e05e',
		legislation: '#81e6d9',
		metric: '#fbb6ce',
		role: '#90cdf4',
		relation_kind: '#e2e8f0'
	};

	let nodes = $state<Node[]>([]);
	let edges = $state<Edge[]>([]);

	let query = $state('');
	let typeFilter = $state('');
	let searchResults = $state<Entity[]>([]);
	let selectedEntity = $state<Entity | null>(null);
	let selectedRelationships = $state<Relationship[]>([]);
	let searching = $state(false);
	let loadedIds = new Set<string>();

	const ENTITY_TYPES = [
		'person', 'organization', 'place', 'topic',
		'asset', 'product', 'legislation', 'metric', 'role', 'relation_kind'
	];

	async function search() {
		if (!query.trim() && !typeFilter) return;
		searching = true;
		try {
			searchResults = await api.entities.list({
				q: query || undefined,
				type: typeFilter || undefined,
				limit: 20
			});
		} finally {
			searching = false;
		}
	}

	async function addEntityToGraph(entity: Entity) {
		if (loadedIds.has(entity.entity_id)) {
			selectNode(entity.entity_id);
			return;
		}
		loadedIds.add(entity.entity_id);

		const color = TYPE_COLORS[entity.entity_type] ?? '#718096';
		const x = 100 + (nodes.length % 5) * 220;
		const y = 80 + Math.floor(nodes.length / 5) * 120;

		nodes = [
			...nodes,
			{
				id: entity.entity_id,
				position: { x, y },
				data: { label: entity.canonical_name, entity },
				style: `background:${color}22;border:2px solid ${color};color:#e2e8f0;border-radius:8px;padding:8px 12px;font-size:13px;`
			}
		];

		const rels = await api.entities.relationships(entity.entity_id);
		for (const rel of rels) {
			const otherId = rel.source_id === entity.entity_id ? rel.target_id : rel.source_id;
			if (loadedIds.has(otherId)) {
				const edgeId = `${rel.source_id}-${rel.relation_type}-${rel.target_id}`;
				if (!edges.find((e) => e.id === edgeId)) {
					edges = [
						...edges,
						{
							id: edgeId,
							source: rel.source_id,
							target: rel.target_id,
							label: rel.relation_type,
							style: 'stroke:#4a5568;',
							labelStyle: 'fill:#a0aec0;font-size:11px;'
						}
					];
				}
			}
		}
	}

	async function selectNode(entityId: string) {
		const node = nodes.find((n) => n.id === entityId);
		if (!node) return;
		selectedEntity = node.data.entity as Entity;
		selectedRelationships = await api.entities.relationships(entityId);
	}

	function handleNodeClick(event: CustomEvent) {
		const { node } = event.detail;
		selectNode(node.id);
	}

	function clearGraph() {
		nodes = [];
		edges = [];
		loadedIds.clear();
		selectedEntity = null;
		selectedRelationships = [];
	}
</script>

<svelte:head><title>KG Graph — Unstructured Mapping</title></svelte:head>

<div class="page">
	<!-- Left sidebar: search -->
	<aside class="search-panel">
		<h2>Entity search</h2>

		<input
			class="input"
			type="text"
			placeholder="Name prefix…"
			bind:value={query}
			onkeydown={(e) => e.key === 'Enter' && search()}
		/>
		<select class="input" bind:value={typeFilter}>
			<option value="">All types</option>
			{#each ENTITY_TYPES as t}<option value={t}>{t}</option>{/each}
		</select>
		<button class="btn" onclick={search} disabled={searching}>
			{searching ? 'Searching…' : 'Search'}
		</button>

		{#if searchResults.length}
			<ul class="results">
				{#each searchResults as e}
					<li>
						<button class="result-item" onclick={() => addEntityToGraph(e)}>
							<span class="dot" style="background:{TYPE_COLORS[e.entity_type] ?? '#718096'}"></span>
							<span class="name">{e.canonical_name}</span>
							<span class="type">{e.entity_type}</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}

		{#if nodes.length}
			<button class="btn btn-ghost" onclick={clearGraph}>Clear graph</button>
		{/if}
	</aside>

	<!-- Graph canvas -->
	<div class="canvas">
		<SvelteFlow {nodes} {edges} onnodeclick={handleNodeClick} fitView>
			<Background />
			<Controls />
		</SvelteFlow>
	</div>

	<!-- Right panel: entity detail -->
	{#if selectedEntity}
		<aside class="detail-panel">
			<button class="close-btn" onclick={() => (selectedEntity = null)}>✕</button>
			<div class="type-badge" style="background:{TYPE_COLORS[selectedEntity.entity_type] ?? '#718096'}22;color:{TYPE_COLORS[selectedEntity.entity_type] ?? '#718096'}">
				{selectedEntity.entity_type}{selectedEntity.subtype ? ` · ${selectedEntity.subtype}` : ''}
			</div>
			<h3>{selectedEntity.canonical_name}</h3>
			{#if selectedEntity.description}
				<p class="desc">{selectedEntity.description}</p>
			{/if}
			{#if selectedEntity.aliases?.length}
				<div class="aliases">
					{#each selectedEntity.aliases as a}<span class="alias">{a}</span>{/each}
				</div>
			{/if}

			<a class="link-btn" href="/entities/{selectedEntity.entity_id}">
				Full detail →
			</a>

			{#if selectedRelationships.length}
				<h4>Relationships ({selectedRelationships.length})</h4>
				<ul class="rel-list">
					{#each selectedRelationships.slice(0, 10) as rel}
						<li>
							<span class="rel-type">{rel.relation_type}</span>
							{#if rel.source_id === selectedEntity?.entity_id}
								→ <button class="inline-btn" onclick={() => addEntityToGraph({ entity_id: rel.target_id } as Entity)}>{rel.target_id.slice(0, 8)}…</button>
							{:else}
								← <button class="inline-btn" onclick={() => addEntityToGraph({ entity_id: rel.source_id } as Entity)}>{rel.source_id.slice(0, 8)}…</button>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</aside>
	{/if}
</div>

<style>
	.page { display: flex; height: calc(100vh - 48px); gap: 0; margin: -24px; overflow: hidden; }
	.search-panel {
		width: 240px; padding: 16px; background: #1a1f2e;
		border-right: 1px solid #2d3748; display: flex;
		flex-direction: column; gap: 8px; overflow-y: auto; flex-shrink: 0;
	}
	.search-panel h2 { font-size: 0.85rem; font-weight: 700; color: #a0aec0; text-transform: uppercase; letter-spacing: 0.05em; }
	.canvas { flex: 1; background: #0f1117; }
	.detail-panel {
		width: 260px; padding: 16px; background: #1a1f2e;
		border-left: 1px solid #2d3748; overflow-y: auto; flex-shrink: 0;
		position: relative;
	}
	.input {
		width: 100%; padding: 8px 10px; background: #0f1117; border: 1px solid #2d3748;
		border-radius: 6px; color: #e2e8f0; font-size: 0.875rem;
	}
	.btn {
		width: 100%; padding: 8px; background: #2b6cb0; color: #fff;
		border: none; border-radius: 6px; cursor: pointer; font-size: 0.875rem;
	}
	.btn:disabled { opacity: 0.5; cursor: default; }
	.btn-ghost { background: transparent; border: 1px solid #2d3748; color: #a0aec0; }
	.results { list-style: none; display: flex; flex-direction: column; gap: 2px; }
	.result-item {
		display: flex; align-items: center; gap: 6px; width: 100%;
		padding: 6px 8px; background: none; border: none; border-radius: 6px;
		cursor: pointer; text-align: left; color: #e2e8f0;
	}
	.result-item:hover { background: #2d3748; }
	.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
	.name { flex: 1; font-size: 0.8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.type { font-size: 0.7rem; color: #718096; }
	.close-btn { position: absolute; top: 12px; right: 12px; background: none; border: none; color: #718096; cursor: pointer; font-size: 1rem; }
	.type-badge { display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; margin-bottom: 8px; }
	.detail-panel h3 { font-size: 1rem; font-weight: 700; margin-bottom: 8px; }
	.detail-panel h4 { font-size: 0.8rem; font-weight: 600; color: #a0aec0; margin: 16px 0 6px; text-transform: uppercase; }
	.desc { font-size: 0.8rem; color: #a0aec0; line-height: 1.5; margin-bottom: 8px; }
	.aliases { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
	.alias { background: #2d3748; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; color: #a0aec0; }
	.link-btn { display: block; padding: 6px 12px; background: #2b6cb0; color: #fff; border-radius: 6px; font-size: 0.8rem; text-align: center; margin-bottom: 8px; }
	.rel-list { list-style: none; display: flex; flex-direction: column; gap: 4px; }
	.rel-list li { font-size: 0.75rem; color: #a0aec0; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
	.rel-type { background: #2d3748; padding: 1px 6px; border-radius: 4px; color: #90cdf4; }
	.inline-btn { background: none; border: none; color: #63b3ed; cursor: pointer; font-size: 0.75rem; text-decoration: underline; }
</style>
