type PageErrorStateProps = {
  title: string;
  detail: string;
};

export function PageErrorState({ title, detail }: PageErrorStateProps) {
  return (
    <section className="section-block">
      <p className="eyebrow">Unavailable</p>
      <h1>{title}</h1>
      <p className="hero-text">{detail}</p>
    </section>
  );
}

export function PageLoadingState() {
  return (
    <div className="page-stack">
      <section className="section-block loading-shell">
        <div className="loading-line loading-line-wide" />
        <div className="loading-line" />
        <div className="loading-line loading-line-short" />
      </section>
      <section className="section-block loading-shell">
        <div className="loading-grid">
          <div className="loading-card" />
          <div className="loading-card" />
          <div className="loading-card" />
        </div>
      </section>
    </div>
  );
}
