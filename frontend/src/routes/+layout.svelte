<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="shell">
	<nav class="sidebar">
		<div class="logo">Unstructured<br />Mapping</div>
		<a href="/">Dashboard</a>
		<a href="/graph">KG Graph</a>
		<a href="/feed">Feed</a>
	</nav>
	<main class="content">
		{@render children()}
	</main>
</div>

<style>
	:global(*, *::before, *::after) {
		box-sizing: border-box;
		margin: 0;
		padding: 0;
	}
	:global(body) {
		font-family: system-ui, sans-serif;
		background: #0f1117;
		color: #e2e8f0;
	}
	:global(a) {
		color: #63b3ed;
		text-decoration: none;
	}
	:global(a:hover) {
		text-decoration: underline;
	}
	.shell {
		display: flex;
		height: 100vh;
	}
	.sidebar {
		width: 180px;
		background: #1a1f2e;
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 20px 12px;
		border-right: 1px solid #2d3748;
		flex-shrink: 0;
	}
	.logo {
		font-size: 0.75rem;
		font-weight: 700;
		color: #90cdf4;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: 20px;
		line-height: 1.4;
	}
	.sidebar a {
		display: block;
		padding: 8px 10px;
		border-radius: 6px;
		color: #a0aec0;
		font-size: 0.875rem;
	}
	.sidebar a:hover {
		background: #2d3748;
		color: #e2e8f0;
		text-decoration: none;
	}
	.content {
		flex: 1;
		overflow: auto;
		padding: 24px;
	}
</style>
