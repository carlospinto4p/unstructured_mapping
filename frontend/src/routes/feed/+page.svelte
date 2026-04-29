<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type Article, type Run } from '$lib/api';

	let articles = $state<Article[]>([]);
	let runs = $state<Run[]>([]);
	let sourceFilter = $state('');
	let loadingArticles = $state(true);
	let loadingRuns = $state(true);
	let entityCount = $state<number | null>(null);

	let populateStatus = $state<{ text: string; kind: 'idle' | 'running' | 'done' | 'error' } | null>(null);
	let ingestStatus = $state<{ text: string; kind: 'idle' | 'running' | 'done' | 'error' } | null>(null);
	let scrapeStatus = $state<{ text: string; kind: 'idle' | 'running' | 'done' | 'error' } | null>(null);
	let ingestProvider = $state('claude');
	let ingestLimit = $state(50);
	let ingestColdStart = $state(false);
	let activeRun = $state<Run | null>(null);

	onMount(async () => {
		await Promise.all([loadArticles(), loadRuns(), loadEntityCount()]);
	});

	async function loadEntityCount() {
		try {
			const health = await api.health();
			entityCount = health.entities.total;
		} catch {
			entityCount = null;
		}
	}

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

	async function triggerPopulate() {
		populateStatus = { text: 'Loading seed entities into KG…', kind: 'running' };
		try {
			const res = await api.kg.populate();
			populateStatus = {
				text: `Done — ${res.total_created} entities added, ${res.total_skipped} already present across ${res.stages.length} stages.`,
				kind: 'done'
			};
			entityCount = (entityCount ?? 0) + res.total_created;
		} catch (e) {
			populateStatus = { text: `Error: ${e}`, kind: 'error' };
		}
	}

	async function triggerScrape() {
		scrapeStatus = { text: 'Fetching articles from BBC, Reuters, AP…', kind: 'running' };
		try {
			const res = await api.scrape.trigger();
			scrapeStatus = { text: `Scraping ${res.sources.join(', ')} in background. Refresh the articles table when complete.`, kind: 'done' };
			setTimeout(loadArticles, 5000);
		} catch (e) {
			scrapeStatus = { text: `Error: ${e}`, kind: 'error' };
		}
	}

	async function triggerIngest() {
		ingestStatus = { text: 'Starting pipeline…', kind: 'running' };
		try {
			await api.runs.ingest({ provider: ingestProvider, limit: ingestLimit, cold_start: ingestColdStart });
			ingestStatus = { text: `Pipeline started (${ingestProvider}, up to ${ingestLimit} articles). Checking for run…`, kind: 'running' };

			const pollInterval = setInterval(async () => {
				const updated = await api.runs.list(20);
				runs = updated;
				const running = updated.find((r) => r.status === 'running');
				if (running) {
					activeRun = running;
					ingestStatus = {
						text: `Run ${running.run_id.slice(0, 8)}… in progress — ${running.document_count} docs processed so far`,
						kind: 'running'
					};
				} else if (activeRun) {
					const finished = updated.find((r) => r.run_id === activeRun?.run_id);
					if (finished && finished.status !== 'running') {
						ingestStatus = {
							text: `Run ${finished.run_id.slice(0, 8)}… ${finished.status} — ${finished.entity_count} entities, ${finished.relationship_count} relationships`,
							kind: finished.status === 'completed' ? 'done' : 'error'
						};
						activeRun = null;
						clearInterval(pollInterval);
					}
				}
			}, 3000);
		} catch (e) {
			ingestStatus = { text: `Error: ${e}`, kind: 'error' };
		}
	}
</script>

<svelte:head><title>Feed — Unstructured Mapping</title></svelte:head>

<h1 class="page-title">Feed</h1>
<p class="subtitle">Three-step pipeline: seed the KG with known entities, scrape articles from news sources, then run the LLM pipeline to extract relationships.</p>

{#if entityCount === 0}
	<div class="empty-kg-warning">
		<strong>KG is empty.</strong> Seed entities first (Step 0) — without entities in the graph, the pipeline cannot detect mentions or extract relationships.
	</div>
{/if}

<div class="pipeline">
	<!-- Step 0 -->
	<div class="step-card">
		<div class="step-number step-zero">0</div>
		<div class="step-body">
			<h2>Seed entities</h2>
			<p class="step-desc">Load the curated financial entities and Wikidata snapshots into the KG. Required once on a fresh database — idempotent, safe to re-run.</p>
			<div class="entity-count">
				{#if entityCount === null}
					<span class="muted">Loading…</span>
				{:else}
					<span class:count-zero={entityCount === 0}>{entityCount} entities in KG</span>
				{/if}
			</div>
			<button class="btn btn-seed" onclick={triggerPopulate} disabled={populateStatus?.kind === 'running'}>
				{populateStatus?.kind === 'running' ? 'Seeding…' : 'Seed entities'}
			</button>
			{#if populateStatus}
				<div class="status-bar {populateStatus.kind}">{populateStatus.text}</div>
			{/if}
		</div>
	</div>

	<div class="arrow">→</div>

	<!-- Step 1 -->
	<div class="step-card">
		<div class="step-number">1</div>
		<div class="step-body">
			<h2>Scrape articles</h2>
			<p class="step-desc">Fetch the latest articles from BBC, Reuters, and AP and store them in the articles database.</p>
			<button class="btn" onclick={triggerScrape} disabled={scrapeStatus?.kind === 'running'}>
				{scrapeStatus?.kind === 'running' ? 'Scraping…' : 'Scrape all sources'}
			</button>
			{#if scrapeStatus}
				<div class="status-bar {scrapeStatus.kind}">{scrapeStatus.text}</div>
			{/if}
		</div>
	</div>

	<div class="arrow">→</div>

	<!-- Step 2 -->
	<div class="step-card">
		<div class="step-number">2</div>
		<div class="step-body">
			<h2>Run pipeline</h2>
			<p class="step-desc">Detect entity mentions in stored articles, resolve them against the KG, and extract relationships using the LLM.</p>
			<div class="field-row">
				<label class="field">
					<span>LLM provider</span>
					<select class="input-sm" bind:value={ingestProvider}>
						<option value="claude">Claude</option>
						<option value="ollama">Ollama</option>
					</select>
				</label>
				<label class="field">
					<span>Max articles</span>
					<input class="input-sm" type="number" bind:value={ingestLimit} min="1" max="500" style="width:80px" />
				</label>
				<label class="field field-checkbox" title="Skip relationship extraction — let the LLM propose new entities from raw text instead. Use on a freshly seeded KG before relationships can be meaningfully extracted.">
					<span>Cold start</span>
					<input type="checkbox" bind:checked={ingestColdStart} />
				</label>
			</div>
			<button class="btn btn-green" onclick={triggerIngest} disabled={ingestStatus?.kind === 'running'}>
				{ingestStatus?.kind === 'running' ? 'Running…' : 'Run pipeline'}
			</button>
			{#if ingestStatus}
				<div class="status-bar {ingestStatus.kind}">{ingestStatus.text}</div>
			{/if}
		</div>
	</div>
</div>

<div class="two-col">
	<!-- Articles -->
	<section>
		<div class="section-header">
			<h3>Scraped articles</h3>
			<div class="filter-row">
				<select class="input-sm" bind:value={sourceFilter} onchange={loadArticles}>
					<option value="">All sources</option>
					<option value="bbc">BBC</option>
					<option value="reuters">Reuters</option>
					<option value="ap">AP</option>
				</select>
				<button class="btn-icon" onclick={loadArticles} title="Refresh">↻</button>
			</div>
		</div>
		{#if loadingArticles}
			<p class="muted">Loading…</p>
		{:else if !articles.length}
			<p class="muted">No articles yet. Run step 1 to scrape.</p>
		{:else}
			<p class="count">{articles.length} articles shown</p>
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
			<h3>Pipeline runs</h3>
			<button class="btn-icon" onclick={loadRuns} title="Refresh">↻</button>
		</div>
		{#if loadingRuns}
			<p class="muted">Loading…</p>
		{:else if !runs.length}
			<p class="muted">No runs yet. Run step 2 to start the pipeline.</p>
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
	.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 6px; }
	.subtitle { color: #718096; font-size: 0.875rem; margin-bottom: 16px; max-width: 640px; line-height: 1.5; }

	.empty-kg-warning {
		background: #2d1a00; color: #f6ad55; border: 1px solid #744210;
		border-radius: 8px; padding: 10px 16px; font-size: 0.8rem;
		line-height: 1.5; margin-bottom: 20px; max-width: 720px;
	}

	.step-zero { background: #553c9a; }
	.btn-seed { background: #553c9a; }

	.entity-count { font-size: 0.8rem; color: #a0aec0; }
	.count-zero { color: #fc8181; font-weight: 600; }

	.pipeline { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 36px; flex-wrap: wrap; }
	.step-card {
		flex: 1; min-width: 260px; background: #1a1f2e;
		border: 1px solid #2d3748; border-radius: 10px;
		padding: 20px; display: flex; gap: 14px;
	}
	.step-number {
		width: 28px; height: 28px; border-radius: 50%;
		background: #2b6cb0; color: #fff; font-weight: 700;
		font-size: 0.875rem; display: flex; align-items: center;
		justify-content: center; flex-shrink: 0; margin-top: 2px;
	}
	.step-body { flex: 1; display: flex; flex-direction: column; gap: 10px; }
	.step-body h2 { font-size: 1rem; font-weight: 700; }
	.step-desc { font-size: 0.8rem; color: #a0aec0; line-height: 1.5; }
	.arrow { font-size: 1.5rem; color: #4a5568; align-self: center; padding: 0 4px; }

	.field-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
	.field { display: flex; flex-direction: column; gap: 4px; font-size: 0.75rem; color: #718096; }
	.field-checkbox { cursor: help; }
	.field-checkbox input { width: 16px; height: 16px; accent-color: #276749; cursor: pointer; }

	.btn { padding: 8px 16px; background: #2b6cb0; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 0.875rem; align-self: flex-start; }
	.btn:disabled { opacity: 0.5; cursor: default; }
	.btn-green { background: #276749; }
	.btn-icon { background: none; border: none; color: #718096; cursor: pointer; font-size: 1.1rem; padding: 4px 6px; }
	.btn-icon:hover { color: #e2e8f0; }
	.input-sm { padding: 6px 10px; background: #0f1117; border: 1px solid #2d3748; border-radius: 6px; color: #e2e8f0; font-size: 0.875rem; }

	.status-bar { padding: 8px 12px; border-radius: 6px; font-size: 0.8rem; line-height: 1.4; }
	.status-bar.running { background: #1a2744; color: #90cdf4; border: 1px solid #2a4365; }
	.status-bar.done    { background: #1a2e22; color: #9ae6b4; border: 1px solid #276749; }
	.status-bar.error   { background: #2d1515; color: #fc8181; border: 1px solid #742a2a; }
	.status-bar.idle    { background: #1a1f2e; color: #a0aec0; }

	.muted { color: #718096; font-size: 0.875rem; }
	.count { font-size: 0.75rem; color: #718096; margin-bottom: 6px; }

	.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
	.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
	.filter-row { display: flex; align-items: center; gap: 4px; }
	h3 { font-size: 0.85rem; font-weight: 700; color: #a0aec0; text-transform: uppercase; letter-spacing: 0.05em; }

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
