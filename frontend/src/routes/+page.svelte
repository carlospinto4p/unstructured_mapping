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

{#if error}
	<div class="alert">Could not reach API: {error}</div>
{:else if !health}
	<p class="muted">Loading…</p>
{:else}
	<div class="grid">
		<div class="card">
			<div class="stat">{health.entities.total.toLocaleString()}</div>
			<div class="label">Entities</div>
		</div>
		<div class="card">
			<div class="stat">{health.relationships.toLocaleString()}</div>
			<div class="label">Relationships</div>
		</div>
		<div class="card">
			<div class="stat">{health.articles.total.toLocaleString()}</div>
			<div class="label">Articles</div>
		</div>
	</div>

	<section class="section">
		<h2>Entities by type</h2>
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
			<table>
				<tbody>
					<tr><td>Run ID</td><td class="mono">{health.latest_run.run_id}</td></tr>
					<tr><td>Status</td><td><span class="badge {health.latest_run.status}">{health.latest_run.status}</span></td></tr>
					<tr><td>Started</td><td>{new Date(health.latest_run.started_at).toLocaleString()}</td></tr>
					<tr><td>Documents</td><td>{health.latest_run.document_count}</td></tr>
					<tr><td>Entities</td><td>{health.latest_run.entity_count}</td></tr>
					<tr><td>Relationships</td><td>{health.latest_run.relationship_count}</td></tr>
				</tbody>
			</table>
		</section>
	{/if}
{/if}

<style>
	.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 24px; }
	.alert { background: #742a2a; color: #fed7d7; padding: 12px 16px; border-radius: 8px; }
	.muted { color: #718096; }
	.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 32px; }
	.card { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 10px; padding: 20px; }
	.stat { font-size: 2rem; font-weight: 700; color: #90cdf4; }
	.label { color: #718096; font-size: 0.85rem; margin-top: 4px; }
	.section { margin-bottom: 32px; }
	.section h2 { font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: #a0aec0; text-transform: uppercase; letter-spacing: 0.05em; }
	table { width: 100%; border-collapse: collapse; background: #1a1f2e; border-radius: 8px; overflow: hidden; }
	th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #2d3748; font-size: 0.875rem; }
	th { color: #718096; font-weight: 600; }
	.mono { font-family: monospace; font-size: 0.8rem; }
	.badge { padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
	.badge.completed { background: #276749; color: #9ae6b4; }
	.badge.running { background: #2a4365; color: #90cdf4; }
	.badge.failed { background: #742a2a; color: #fc8181; }
</style>
