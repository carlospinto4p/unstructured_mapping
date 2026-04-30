<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type HealthResponse } from '$lib/api';

	let health = $state<HealthResponse | null>(null);
	let error = $state<string | null>(null);

	onMount(async () => {
		try {
			health = await api.health();
		} catch (e) {
			error = String(e);
		}
	});
</script>

<svelte:head><title>Dashboard — Unstructured Mapping</title></svelte:head>

<h1 class="page-title">Dashboard</h1>
<p class="intro">
	Unstructured Mapping reads news articles and builds a <strong>Knowledge Graph (KG)</strong> from
	them. The pipeline detects entity mentions in text, resolves them to known graph nodes, and
	extracts relationships between those nodes using an LLM. This dashboard shows a live snapshot of
	what is currently in the graph.
</p>

{#if error}
	<div class="alert">Could not reach API: {error}</div>
{:else if !health}
	<p class="muted">Loading…</p>
{:else}
	<div class="grid">
		<div class="card">
			<div class="stat">{health.entities.total.toLocaleString()}</div>
			<div class="label">Entities</div>
			<div class="card-hint">Named real-world objects in the graph — people, organisations, assets, places, and more.</div>
		</div>
		<div class="card">
			<div class="stat">{health.relationships.toLocaleString()}</div>
			<div class="label">Relationships</div>
			<div class="card-hint">Directed connections between entity pairs, extracted by the LLM from article text.</div>
		</div>
		<div class="card">
			<div class="stat">{health.articles.total.toLocaleString()}</div>
			<div class="label">Articles</div>
			<div class="card-hint">Raw news articles that have been scraped and stored. Not all may have been processed by the pipeline yet.</div>
		</div>
	</div>

	<section class="section">
		<h2>Entities by type</h2>
		<p class="section-hint">Each entity is assigned a type when it is added to the graph. The type controls how the LLM resolves mentions and which relationship kinds make sense.</p>
		<table>
			<thead><tr><th>Type</th><th>Count</th></tr></thead>
			<tbody>
				{#each Object.entries(health.entities.by_type).sort((a, b) => b[1] - a[1]) as [type, count]}
					<tr><td>{type}</td><td>{count.toLocaleString()}</td></tr>
				{/each}
			</tbody>
		</table>
	</section>

	<section class="section">
		<h2>Articles by source</h2>
		<p class="section-hint">Articles are scraped from multiple news feeds. Use the <a href="/feed">Feed page</a> to trigger a fresh scrape.</p>
		<table>
			<thead><tr><th>Source</th><th>Count</th></tr></thead>
			<tbody>
				{#each Object.entries(health.articles.by_source) as [src, count]}
					<tr><td>{src}</td><td>{count.toLocaleString()}</td></tr>
				{/each}
			</tbody>
		</table>
	</section>

	{#if health.latest_run}
		<section class="section">
			<h2>Latest run</h2>
			<p class="section-hint">A <em>run</em> is one execution of the LLM pipeline over a batch of articles. Each run records which model was used, how many documents it processed, and the entities and relationships it produced.</p>
			<table>
				<tbody>
					<tr><td>Run ID</td><td class="mono">{health.latest_run.run_id}</td></tr>
					<tr><td>Status</td><td><span class="badge {health.latest_run.status}">{health.latest_run.status}</span></td></tr>
					<tr><td>Started</td><td>{new Date(health.latest_run.started_at).toLocaleString()}</td></tr>
					<tr>
						<td>Documents processed</td>
						<td>{health.latest_run.document_count}
							<span class="row-hint">articles sent through the pipeline</span>
						</td>
					</tr>
					<tr>
						<td>Entities found</td>
						<td>{health.latest_run.entity_count}
							<span class="row-hint">new or matched entity mentions</span>
						</td>
					</tr>
					<tr>
						<td>Relationships found</td>
						<td>{health.latest_run.relationship_count}
							<span class="row-hint">new relationships written to the graph</span>
						</td>
					</tr>
				</tbody>
			</table>
		</section>
	{/if}
{/if}

<style>
	.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 10px; }
	.intro { color: #a0aec0; font-size: 0.875rem; line-height: 1.65; max-width: 680px; margin-bottom: 28px; }
	.intro strong { color: #e2e8f0; }
	.alert { background: #742a2a; color: #fed7d7; padding: 12px 16px; border-radius: 8px; }
	.muted { color: #718096; }

	.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 32px; }
	.card { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 10px; padding: 20px; }
	.stat { font-size: 2rem; font-weight: 700; color: #90cdf4; }
	.label { color: #718096; font-size: 0.85rem; margin-top: 4px; font-weight: 600; }
	.card-hint { color: #4a5568; font-size: 0.75rem; margin-top: 8px; line-height: 1.5; }

	.section { margin-bottom: 32px; }
	.section h2 { font-size: 1rem; font-weight: 600; margin-bottom: 6px; color: #a0aec0; text-transform: uppercase; letter-spacing: 0.05em; }
	.section-hint { font-size: 0.78rem; color: #4a5568; margin-bottom: 10px; line-height: 1.5; }
	.section-hint a { color: #63b3ed; }

	table { width: 100%; border-collapse: collapse; background: #1a1f2e; border-radius: 8px; overflow: hidden; }
	th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #2d3748; font-size: 0.875rem; }
	th { color: #718096; font-weight: 600; }
	.mono { font-family: monospace; font-size: 0.8rem; }
	.row-hint { color: #4a5568; font-size: 0.75rem; margin-left: 6px; }

	.badge { padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
	.badge.completed { background: #276749; color: #9ae6b4; }
	.badge.running { background: #2a4365; color: #90cdf4; }
	.badge.failed { background: #742a2a; color: #fc8181; }
</style>
