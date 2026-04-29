<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type Article, type Run } from '$lib/api';

	let articles = $state<Article[]>([]);
	let runs = $state<Run[]>([]);
	let sourceFilter = $state('');
	let loadingArticles = $state(true);
	let loadingRuns = $state(true);

	let ingestStatus = $state<string | null>(null);
	let scrapeStatus = $state<string | null>(null);
	let ingestProvider = $state('claude');
	let ingestLimit = $state(50);
	let activeRun = $state<Run | null>(null);

	onMount(async () => {
		await Promise.all([loadArticles(), loadRuns()]);
	});

	async function loadArticles() {
		loadingArticles = true;
		try {
			articles = await api.scrape.articles({ source: sourceFilter || undefined, limit: 50 });
		} finally {
			loadingArticles = false;
		}
	}

	async function loadRuns() {
		loadingRuns = true;
		try {
			runs = await api.runs.list(20);
		} finally {
			loadingRuns = false;
		}
	}

	async function triggerScrape() {
		scrapeStatus = 'starting…';
		try {
			const res = await api.scrape.trigger();
			scrapeStatus = `Scraping ${res.sources.join(', ')} — ${res.message}`;
		} catch (e) {
			scrapeStatus = `Error: ${e}`;
		}
	}

	async function triggerIngest() {
		ingestStatus = 'Starting…';
		try {
			const res = await api.runs.ingest({
				provider: ingestProvider,
				limit: ingestLimit
			});
			ingestStatus = res.message;
			// Poll runs list every 3 s until a new run appears
			const pollInterval = setInterval(async () => {
				const updated = await api.runs.list(20);
				runs = updated;
				const running = updated.find((r) => r.status === 'running');
				if (running) {
					activeRun = running;
					ingestStatus = `Run ${running.run_id.slice(0, 8)}… — running`;
				} else if (activeRun) {
					const finished = updated.find((r) => r.run_id === activeRun?.run_id);
					if (finished && finished.status !== 'running') {
						ingestStatus = `Run ${finished.run_id.slice(0, 8)}… — ${finished.status}`;
						activeRun = null;
						clearInterval(pollInterval);
					}
				}
			}, 3000);
		} catch (e) {
			ingestStatus = `Error: ${e}`;
		}
	}
</script>

<svelte:head><title>Feed — Unstructured Mapping</title></svelte:head>

<h1 class="page-title">Feed</h1>

<div class="controls-row">
	<div class="control-group">
		<button class="btn" onclick={triggerScrape}>Scrape all sources</button>
		{#if scrapeStatus}
			<span class="status-msg">{scrapeStatus}</span>
		{/if}
	</div>

	<div class="control-group">
		<select class="input-sm" bind:value={ingestProvider}>
			<option value="claude">Claude</option>
			<option value="ollama">Ollama</option>
		</select>
		<input class="input-sm" type="number" bind:value={ingestLimit} min="1" max="500" style="width:70px" />
		<button class="btn btn-green" onclick={triggerIngest}>Ingest</button>
		{#if ingestStatus}
			<span class="status-msg">{ingestStatus}</span>
		{/if}
	</div>
</div>

<div class="two-col">
	<!-- Articles -->
	<section>
		<div class="section-header">
			<h2>Articles</h2>
			<div class="filter-row">
				<select class="input-sm" bind:value={sourceFilter} onchange={loadArticles}>
					<option value="">All sources</option>
					<option value="bbc">BBC</option>
					<option value="reuters">Reuters</option>
					<option value="ap">AP</option>
				</select>
				<button class="btn-icon" onclick={loadArticles}>↻</button>
			</div>
		</div>
		{#if loadingArticles}
			<p class="muted">Loading…</p>
		{:else if !articles.length}
			<p class="muted">No articles. Try scraping first.</p>
		{:else}
			<table>
				<thead>
					<tr><th>Source</th><th>Title</th><th>Published</th></tr>
				</thead>
				<tbody>
					{#each articles as a}
						<tr>
							<td><span class="source-badge">{a.source}</span></td>
							<td class="title-cell">
								<a href={a.url} target="_blank" rel="noopener">{a.title}</a>
							</td>
							<td class="date-cell">
								{a.published ? new Date(a.published).toLocaleDateString() : '—'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>

	<!-- Runs -->
	<section>
		<div class="section-header">
			<h2>Ingestion runs</h2>
			<button class="btn-icon" onclick={loadRuns}>↻</button>
		</div>
		{#if loadingRuns}
			<p class="muted">Loading…</p>
		{:else if !runs.length}
			<p class="muted">No runs yet.</p>
		{:else}
			<table>
				<thead>
					<tr><th>Run</th><th>Status</th><th>Docs</th><th>Entities</th><th>Relations</th><th>Started</th></tr>
				</thead>
				<tbody>
					{#each runs as run}
						<tr class:active-row={run.status === 'running'}>
							<td class="mono">{run.run_id.slice(0, 8)}…</td>
							<td><span class="badge {run.status}">{run.status}</span></td>
							<td>{run.document_count}</td>
							<td>{run.entity_count}</td>
							<td>{run.relationship_count}</td>
							<td class="date-cell">{new Date(run.started_at).toLocaleString()}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>
</div>

<style>
	.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; }
	.controls-row { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 24px; align-items: center; }
	.control-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.btn { padding: 8px 16px; background: #2b6cb0; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 0.875rem; white-space: nowrap; }
	.btn-green { background: #276749; }
	.btn-icon { background: none; border: none; color: #718096; cursor: pointer; font-size: 1.1rem; padding: 4px 6px; }
	.btn-icon:hover { color: #e2e8f0; }
	.input-sm { padding: 6px 10px; background: #1a1f2e; border: 1px solid #2d3748; border-radius: 6px; color: #e2e8f0; font-size: 0.875rem; }
	.status-msg { font-size: 0.8rem; color: #a0aec0; }
	.muted { color: #718096; font-size: 0.875rem; }
	.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
	.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
	.filter-row { display: flex; align-items: center; gap: 4px; }
	h2 { font-size: 0.85rem; font-weight: 700; color: #a0aec0; text-transform: uppercase; letter-spacing: 0.05em; }
	table { width: 100%; border-collapse: collapse; background: #1a1f2e; border-radius: 8px; overflow: hidden; font-size: 0.8rem; }
	th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #2d3748; }
	th { color: #718096; font-weight: 600; }
	.title-cell { max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.date-cell { white-space: nowrap; color: #718096; }
	.mono { font-family: monospace; font-size: 0.75rem; }
	.source-badge { background: #2d3748; padding: 1px 6px; border-radius: 4px; font-size: 0.7rem; color: #a0aec0; }
	.badge { padding: 2px 8px; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; }
	.badge.completed { background: #276749; color: #9ae6b4; }
	.badge.running { background: #2a4365; color: #90cdf4; }
	.badge.failed { background: #742a2a; color: #fc8181; }
	.active-row { background: #1a2744; }
</style>
