interface ImageViewerProps {
  alt: string;
  src: string;
}

export function ImageViewer({ alt, src }: ImageViewerProps) {
  return (
    <figure style={{ margin: 0 }}>
      <img
        src={src}
        alt={alt}
        loading="lazy"
        style={{ maxWidth: '100%', borderRadius: 4, border: '1px solid #ddd' }}
      />
      {alt ? <figcaption style={{ fontSize: 12, color: '#555' }}>{alt}</figcaption> : null}
    </figure>
  );
}
