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
	let wikidataStatus = $state<{ text: string; kind: 'idle' | 'running' | 'done' | 'error' } | null>(null);
	let aliasAuditStatus = $state<{ text: string; kind: 'idle' | 'running' | 'done' | 'error' } | null>(null);
	let aliasCollisions = $state<import('$lib/api').AliasCollision[]>([]);
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

	async function triggerWikidataRefresh() {
		wikidataStatus = { text: 'Querying Wikidata SPARQL for all entity types… (this may take 1–2 minutes)', kind: 'running' };
		try {
			const res = await api.kg.wikidataRefresh();
			const errors = res.types.filter((t) => t.error !== null);
			if (errors.length) {
				wikidataStatus = {
					text: `Completed with ${errors.length} error(s): ${errors.map((e) => e.type).join(', ')}. ${res.total_created} created, ${res.total_skipped} skipped.`,
					kind: 'error'
				};
			} else {
				wikidataStatus = {
					text: `Done — ${res.total_created} entities added, ${res.total_skipped} already present across ${res.types.length} types.`,
					kind: 'done'
				};
			}
		} catch (e) {
			wikidataStatus = { text: `Error: ${e}`, kind: 'error' };
		}
	}

	async function runAliasAudit() {
		aliasAuditStatus = { text: 'Scanning for alias collisions…', kind: 'running' };
		aliasCollisions = [];
		try {
			const res = await api.kg.aliasAudit();
			aliasCollisions = res.collisions;
			aliasAuditStatus =
				res.total === 0
					? { text: 'No alias collisions found.', kind: 'done' }
					: { text: `${res.total} collision(s) found — see table below.`, kind: res.collisions.some((c) => c.same_type) ? 'error' : 'done' };
		} catch (e) {
			aliasAuditStatus = { text: `Error: ${e}`, kind: 'error' };
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
<p class="subtitle">
	Three-step pipeline: seed the KG with known entities, scrape articles from news sources, then
	run the LLM pipeline to extract relationships. Follow the steps in order on a fresh database.
	Each step is safe to re-run — seeding and scraping are idempotent; duplicate articles and
	entities are silently skipped.
</p>

<details class="workflow-guide" open={entityCount === 0 || entityCount === null}>
	<summary>Workflow guide — how to populate the KG</summary>
	<div class="workflow-body">

		<div class="workflow-phase">
			<div class="phase-label phase-setup">First time setup</div>
			<ol class="phase-steps">
				<li>
					<strong>Seed the KG (Step 0).</strong> Click "Seed entities" to load the curated
					financial entity list and Wikidata snapshots. This gives the pipeline a set of known
					entities to match against. You must do this before running the pipeline — without
					entities in the graph, the detector has nothing to find.
				</li>
				<li>
					<strong>Scrape articles (Step 1).</strong> Click "Scrape all sources" to fetch the
					latest articles from BBC, Reuters, and AP.
					<span class="phase-note">
						Note: Reuters articles only contain a headline and a short summary (1–2 sentences)
						because Reuters blocks full-text scraping. BBC and AP deliver full article body text.
					</span>
				</li>
				<li>
					<strong>Cold-start pass (Step 2, Cold start ON).</strong> Enable the "Cold start"
					checkbox and run the pipeline. In this mode the LLM reads raw article text and
					<em>proposes new entities</em> it finds — people, companies, assets — that aren't yet
					in the seed data. No relationships are extracted in this pass. Run it over a large
					batch of articles (100–200) to build up good entity coverage.
				</li>
				<li>
					<strong>Steady-state pass (Step 2, Cold start OFF).</strong> Disable Cold start and
					run the pipeline again over the same (or new) articles. Now that the KG has entities
					from both seeding and cold-start discovery, the pipeline will detect mentions, resolve
					them to specific entities, and <em>extract relationships</em> between them.
					Relationships only appear after this step.
				</li>
			</ol>
		</div>

		<div class="workflow-phase">
			<div class="phase-label phase-ongoing">Ongoing operation</div>
			<ol class="phase-steps">
				<li>
					<strong>Scrape fresh articles regularly (Step 1)</strong> to keep the article database
					up to date. Articles already in the database are skipped automatically.
				</li>
				<li>
					<strong>Run the pipeline in steady-state mode (Step 2, Cold start OFF)</strong> on new
					articles. Processed articles are also skipped, so you can safely re-run without
					double-counting.
				</li>
				<li>
					<strong>Occasionally run a cold-start pass</strong> if news coverage drifts to new
					entities that aren't in the graph yet (new companies, new people entering the news).
					Follow it with a steady-state pass to extract their relationships.
				</li>
			</ol>
		</div>

		<div class="workflow-phase">
			<div class="phase-label phase-maintenance">Quality maintenance</div>
			<ol class="phase-steps">
				<li>
					<strong>Run the alias collision audit</strong> (KG Maintenance below) after each
					cold-start batch. Cold start may create near-duplicate entities with slightly different
					names for the same real-world object. The audit flags aliases shared by multiple
					entities — same-type collisions are the ones to investigate first.
				</li>
				<li>
					<strong>Refresh Wikidata snapshots</strong> periodically to pick up newly listed
					companies, new central bank governors, and other changes to the financial landscape.
				</li>
			</ol>
		</div>

		<p class="workflow-footer">
			Use the <a href="/graph">KG Graph</a> to inspect entities and their relationships, and the
			entity detail pages to review individual mentions and confidence scores.
		</p>
	</div>
</details>

{#if entityCount === 0}
	<div class="empty-kg-warning">
		<strong>KG is empty.</strong> Start with Step 0 below — see the workflow guide above for the
		full recommended sequence.
	</div>
{/if}

<div class="pipeline">
	<!-- Step 0 -->
	<div class="step-card">
		<div class="step-number step-zero">0</div>
		<div class="step-body">
			<h2>Seed entities</h2>
			<p class="step-desc">
				Load the curated financial entities (companies, indices, people) and Wikidata snapshots
				into the KG. This step is required once on a fresh database. Re-running it is safe —
				entities that already exist are skipped. <strong>The pipeline cannot find mentions without
				entities in the graph.</strong>
			</p>
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
			<p class="step-desc">
				Fetch the latest articles from BBC, Reuters, and AP and store them in the articles
				database. Scraping runs in the background — the articles table below refreshes
				automatically after a few seconds. Articles already in the database are not duplicated.
			</p>
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
			<p class="step-desc">
				Detect entity mentions in stored articles, resolve them against the KG, and extract
				relationships using the LLM. The pipeline runs in the background — progress is shown
				below and the runs table updates every few seconds.
			</p>
			<div class="field-row">
				<label class="field">
					<span>LLM provider</span>
					<select class="input-sm" bind:value={ingestProvider}>
						<option value="claude">Claude (Anthropic API)</option>
						<option value="ollama">Ollama (local model)</option>
					</select>
				</label>
				<label class="field">
					<span>Max articles</span>
					<input class="input-sm" type="number" bind:value={ingestLimit} min="1" max="500" style="width:80px" />
				</label>
				<label class="field">
					<span>Cold start</span>
					<input type="checkbox" bind:checked={ingestColdStart} />
				</label>
			</div>
			{#if ingestColdStart}
				<p class="cold-start-hint">
					<strong>Cold start mode:</strong> the LLM proposes new entities from raw text instead
					of extracting relationships. Use this on a freshly seeded KG where the entity coverage
					is still sparse — it lets the model discover entities the seed data missed before you
					start extracting relationships.
				</p>
			{:else}
				<p class="cold-start-hint muted">
					<strong>Cold start off</strong> (default): the pipeline resolves mentions against
					existing entities and extracts relationships between them.
				</p>
			{/if}
			<button class="btn btn-green" onclick={triggerIngest} disabled={ingestStatus?.kind === 'running'}>
				{ingestStatus?.kind === 'running' ? 'Running…' : 'Run pipeline'}
			</button>
			{#if ingestStatus}
				<div class="status-bar {ingestStatus.kind}">{ingestStatus.text}</div>
			{/if}
		</div>
	</div>
</div>

<details class="maintenance">
	<summary>KG Maintenance</summary>
	<div class="maintenance-body">
		<p class="maint-section-desc">
			These operations maintain the quality of the Knowledge Graph over time. They are not part
			of the normal ingestion pipeline and should be run manually when needed.
		</p>
		<div class="maint-row">
			<div>
				<strong>Refresh Wikidata snapshots</strong>
				<p class="maint-desc">
					Re-fetch all entity types from the Wikidata SPARQL endpoint, overwrite local snapshot
					files, and import new rows into the KG. Entities already in the graph are skipped;
					only genuinely new Wikidata entries are added. Takes 1–2 minutes because it queries
					multiple entity types sequentially.
				</p>
			</div>
			<div class="maint-actions">
				<button class="btn" onclick={triggerWikidataRefresh} disabled={wikidataStatus?.kind === 'running'}>
					{wikidataStatus?.kind === 'running' ? 'Refreshing…' : 'Refresh Wikidata'}
				</button>
				{#if wikidataStatus}
					<div class="status-bar {wikidataStatus.kind}">{wikidataStatus.text}</div>
				{/if}
			</div>
		</div>

		<div class="maint-row">
			<div>
				<strong>Alias collision audit</strong>
				<p class="maint-desc">
					Find aliases shared by more than one entity, ranked by how often the alias appears
					in article mentions. A collision means two entities have the same surface form —
					the pipeline may resolve mentions to the wrong entity. <em>Same-type collisions</em>
					(marked ⚠) are the most serious: two entities of the same type sharing an alias
					are likely duplicates that should be merged. Cross-type collisions (e.g. a person
					and an organisation sharing an acronym) are usually harmless.
				</p>
			</div>
			<div class="maint-actions">
				<button class="btn" onclick={runAliasAudit} disabled={aliasAuditStatus?.kind === 'running'}>
					{aliasAuditStatus?.kind === 'running' ? 'Scanning…' : 'Run audit'}
				</button>
				{#if aliasAuditStatus}
					<div class="status-bar {aliasAuditStatus.kind}">{aliasAuditStatus.text}</div>
				{/if}
			</div>
		</div>

		{#if aliasCollisions.length > 0}
			<p class="maint-desc" style="margin-bottom:8px">
				<strong>Alias</strong> — the shared surface form.
				<strong>Mentions</strong> — total article mentions across all entities with this alias.
				<strong>Same type?</strong> — ⚠ means both entities have the same type (likely a duplicate).
				<strong>Keep</strong> badge marks the entity with the most mentions (the likely canonical one).
			</p>
			<table class="audit-table">
				<thead>
					<tr><th>Alias</th><th>Mentions</th><th>Same type?</th><th>Entities</th></tr>
				</thead>
				<tbody>
					{#each aliasCollisions as c}
						<tr class:collision-same-type={c.same_type}>
							<td class="mono">{c.alias}</td>
							<td>{c.total_mentions}</td>
							<td>{c.same_type ? '⚠ yes' : 'no'}</td>
							<td>
								{#each c.entities as e}
									<div class:merge-target={e.is_merge_target}>
										<a href="/entities/{e.entity_id}">{e.canonical_name}</a>
										<span class="source-badge">{e.entity_type}</span>
										{#if e.is_merge_target}<span class="keep-badge">keep</span>{/if}
									</div>
								{/each}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>
</details>

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
		<p class="panel-hint">Articles stored in the database. Titles link to the original source. Use step 1 above to fetch new ones.</p>
		{#if loadingArticles}
			<p class="muted">Loading…</p>
		{:else if !articles.length}
			<p class="muted">No articles yet. Run step 1 to scrape.</p>
		{:else}
			<p class="count">{articles.length} articles shown (most recent 50)</p>
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
		<p class="panel-hint">Each row is one execution of the LLM pipeline. <strong>Docs</strong> = articles processed. <strong>Entities</strong> = mentions found. <strong>Relations</strong> = relationships written to the graph.</p>
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

	/* Workflow guide */
	.workflow-guide {
		background: #141920; border: 1px solid #2d3748; border-radius: 10px;
		margin-bottom: 20px;
	}
	.workflow-guide summary {
		padding: 12px 20px; font-size: 0.8rem; font-weight: 700;
		color: #a0aec0; text-transform: uppercase; letter-spacing: 0.05em;
		cursor: pointer; user-select: none;
	}
	.workflow-guide summary:hover { color: #e2e8f0; }
	.workflow-body {
		padding: 0 20px 20px;
		display: flex; flex-direction: column; gap: 20px;
	}
	.workflow-phase { display: flex; flex-direction: column; gap: 8px; }
	.phase-label {
		font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.06em; padding: 2px 8px; border-radius: 4px;
		align-self: flex-start;
	}
	.phase-setup      { background: #1a2744; color: #90cdf4; border: 1px solid #2a4365; }
	.phase-ongoing    { background: #1a2e22; color: #9ae6b4; border: 1px solid #276749; }
	.phase-maintenance { background: #2d2a00; color: #f6e05e; border: 1px solid #744210; }
	.phase-steps {
		margin: 0; padding-left: 20px;
		display: flex; flex-direction: column; gap: 8px;
	}
	.phase-steps li { font-size: 0.8rem; color: #a0aec0; line-height: 1.6; }
	.phase-steps li strong { color: #e2e8f0; }
	.phase-steps li em { color: #90cdf4; font-style: normal; font-weight: 600; }
	.phase-note {
		display: block; margin-top: 4px;
		font-size: 0.75rem; color: #718096;
		padding-left: 4px; border-left: 2px solid #2d3748;
	}
	.workflow-footer { font-size: 0.78rem; color: #4a5568; line-height: 1.5; padding-top: 4px; border-top: 1px solid #1a1f2e; }
	.workflow-footer a { color: #63b3ed; }

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
	.step-desc strong { color: #e2e8f0; }
	.cold-start-hint { font-size: 0.75rem; line-height: 1.5; padding: 8px 10px; border-radius: 6px; background: #1a2744; border: 1px solid #2a4365; color: #90cdf4; }
	.cold-start-hint.muted { background: #1a1f2e; border-color: #2d3748; color: #4a5568; }
	.cold-start-hint strong { color: inherit; }
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

	.maintenance {
		background: #1a1f2e; border: 1px solid #2d3748; border-radius: 10px;
		margin-bottom: 28px;
	}
	.maintenance summary {
		padding: 12px 20px; font-size: 0.8rem; font-weight: 700;
		color: #a0aec0; text-transform: uppercase; letter-spacing: 0.05em;
		cursor: pointer; user-select: none;
	}
	.maintenance summary:hover { color: #e2e8f0; }
	.maintenance-body { padding: 0 20px 20px; display: flex; flex-direction: column; gap: 20px; }
	.maint-row { display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap; }
	.maint-row > div:first-child { flex: 1; min-width: 200px; }
	.maint-row strong { font-size: 0.875rem; }
	.maint-section-desc { font-size: 0.78rem; color: #718096; line-height: 1.5; margin-bottom: 4px; }
	.maint-desc { font-size: 0.75rem; color: #718096; margin-top: 4px; line-height: 1.5; }
	.panel-hint { font-size: 0.75rem; color: #4a5568; line-height: 1.5; margin-bottom: 8px; }
	.panel-hint strong { color: #718096; }
	.maint-actions { display: flex; flex-direction: column; gap: 8px; min-width: 260px; }

	.audit-table { width: 100%; border-collapse: collapse; font-size: 0.75rem; margin-top: 8px; }
	.audit-table th, .audit-table td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #2d3748; vertical-align: top; }
	.audit-table th { color: #718096; font-weight: 600; }
	.collision-same-type { background: #2d1a00; }
	.merge-target { font-weight: 600; }
	.keep-badge { background: #276749; color: #9ae6b4; padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; margin-left: 4px; }

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
