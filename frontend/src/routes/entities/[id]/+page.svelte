<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { api, type Entity, type Relationship, type Provenance } from '$lib/api';

	const TYPE_COLORS: Record<string, string> = {
		person: '#4299e1', organization: '#48bb78', place: '#ed8936',
		topic: '#9f7aea', asset: '#fc8181', product: '#f6e05e',
		legislation: '#81e6d9', metric: '#fbb6ce', role: '#90cdf4', relation_kind: '#e2e8f0'
	};

	let entity = $state<Entity | null>(null);
	let relationships = $state<Relationship[]>([]);
	let provenance = $state<Provenance[]>([]);
	let error = $state<string | null>(null);
	let tab = $state<'relationships' | 'mentions'>('relationships');

	const entityId = $derived($page.params.id);

	onMount(async () => {
		try {
			[entity, relationships, provenance] = await Promise.all([
				api.entities.get(entityId),
				api.entities.relationships(entityId),
				api.entities.provenance(entityId)
			]);
		} catch (e) {
			error = String(e);
		}
	});
</script>

<svelte:head>
	<title>{entity?.canonical_name ?? 'Entity'} — Unstructured Mapping</title>
</svelte:head>

{#if error}
	<div class="alert">Error: {error}</div>
{:else if !entity}
	<p class="muted">Loading…</p>
{:else}
	<a class="back-link" href="/graph">← Back to graph</a>

	<header class="entity-header">
		<div
			class="type-badge"
			style="background:{TYPE_COLORS[entity.entity_type] ?? '#718096'}22;color:{TYPE_COLORS[entity.entity_type] ?? '#718096'}"
		>
			{entity.entity_type}{entity.subtype ? ` · ${entity.subtype}` : ''}
		</div>
		<h1>{entity.canonical_name}</h1>
		<span class="status-badge {entity.status}">{entity.status}</span>
		{#if entity.description}
			<p class="description">{entity.description}</p>
		{/if}
		{#if entity.aliases?.length}
			<div class="aliases">
				<span class="dim">Also known as:</span>
				{#each entity.aliases as alias}<span class="alias">{alias}</span>{/each}
			</div>
		{/if}
		<div class="meta-row">
			<span>{relationships.length} relationships</span>
			<span>·</span>
			<span>{provenance.length} mentions</span>
			{#if entity.created_at}
				<span>·</span>
				<span>Created {new Date(entity.created_at).toLocaleDateString()}</span>
			{/if}
		</div>
	</header>

	<div class="tabs">
		<button class="tab" class:active={tab === 'relationships'} onclick={() => (tab = 'relationships')}>
			Relationships ({relationships.length})
		</button>
		<button class="tab" class:active={tab === 'mentions'} onclick={() => (tab = 'mentions')}>
			Mentions ({provenance.length})
		</button>
	</div>

	{#if tab === 'relationships'}
		{#if !relationships.length}
			<p class="muted">No relationships.</p>
		{:else}
			<table>
				<thead>
					<tr>
						<th>Direction</th>
						<th>Entity</th>
						<th>Relation</th>
						<th>Confidence</th>
						<th>Since</th>
					</tr>
				</thead>
				<tbody>
					{#each relationships as rel}
						<tr>
							<td class="dir">
								{rel.source_id === entity.entity_id ? '→ out' : '← in'}
							</td>
							<td>
								{#if rel.source_id === entity.entity_id}
									<a href="/entities/{rel.target_id}">{rel.target_id.slice(0, 12)}…</a>
								{:else}
									<a href="/entities/{rel.source_id}">{rel.source_id.slice(0, 12)}…</a>
								{/if}
							</td>
							<td><span class="rel-type">{rel.relation_type}</span></td>
							<td>{rel.confidence != null ? (rel.confidence * 100).toFixed(0) + '%' : '—'}</td>
							<td class="date-cell">
								{rel.valid_from ? new Date(rel.valid_from).toLocaleDateString() : '—'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{:else}
		{#if !provenance.length}
			<p class="muted">No mentions.</p>
		{:else}
			<div class="mention-list">
				{#each provenance as prov}
					<div class="mention-card">
						<div class="mention-header">
							<span class="source-badge">{prov.source}</span>
							<span class="mention-text">"{prov.mention_text}"</span>
							{#if prov.detected_at}
								<span class="date-cell">{new Date(prov.detected_at).toLocaleDateString()}</span>
							{/if}
						</div>
						<blockquote class="snippet">{prov.context_snippet}</blockquote>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
{/if}

<style>
	.alert { background: #742a2a; color: #fed7d7; padding: 12px 16px; border-radius: 8px; }
	.muted { color: #718096; font-size: 0.875rem; }
	.back-link { font-size: 0.8rem; color: #718096; display: block; margin-bottom: 16px; }
	.entity-header { margin-bottom: 24px; }
	.type-badge { display: inline-block; padding: 3px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin-bottom: 8px; }
	h1 { font-size: 1.75rem; font-weight: 700; margin-bottom: 8px; }
	.status-badge { padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
	.status-badge.active { background: #276749; color: #9ae6b4; }
	.status-badge.merged { background: #2a4365; color: #90cdf4; }
	.status-badge.deprecated { background: #4a5568; color: #a0aec0; }
	.description { color: #a0aec0; margin: 12px 0; line-height: 1.6; max-width: 700px; }
	.aliases { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
	.dim { color: #718096; font-size: 0.8rem; }
	.alias { background: #2d3748; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; color: #a0aec0; }
	.meta-row { display: flex; gap: 8px; font-size: 0.8rem; color: #718096; margin-top: 8px; }
	.tabs { display: flex; gap: 4px; margin-bottom: 16px; }
	.tab { padding: 8px 16px; background: none; border: 1px solid #2d3748; border-radius: 6px; color: #718096; cursor: pointer; font-size: 0.875rem; }
	.tab.active { background: #2b6cb0; border-color: #2b6cb0; color: #fff; }
	table { width: 100%; border-collapse: collapse; background: #1a1f2e; border-radius: 8px; overflow: hidden; font-size: 0.85rem; }
	th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #2d3748; }
	th { color: #718096; font-weight: 600; }
	.dir { color: #718096; font-size: 0.75rem; white-space: nowrap; }
	.rel-type { background: #2d3748; padding: 2px 8px; border-radius: 4px; color: #90cdf4; font-size: 0.8rem; }
	.date-cell { color: #718096; white-space: nowrap; }
	.source-badge { background: #2d3748; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; color: #a0aec0; }
	.mention-list { display: flex; flex-direction: column; gap: 12px; }
	.mention-card { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 8px; padding: 14px 16px; }
	.mention-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
	.mention-text { font-style: italic; color: #e2e8f0; font-size: 0.875rem; }
	.snippet { border-left: 3px solid #2d3748; padding-left: 12px; color: #a0aec0; font-size: 0.8rem; line-height: 1.6; margin: 0; }
</style>
