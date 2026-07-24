import { Alert } from '@cloudscape-design/components';
import { useState } from 'react';

interface ImageViewerProps {
  alt: string;
  src: string;
}

export function ImageViewer({ alt, src }: ImageViewerProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <Alert type="error">{alt || 'Chart'} could not be loaded.</Alert>;
  }

  return (
    <figure style={{ margin: 0 }}>
      <img
        src={src}
        alt={alt}
        loading="eager"
        onError={() => setFailed(true)}
        style={{ maxWidth: '100%', borderRadius: 4, border: '1px solid #ddd' }}
      />
      {alt ? <figcaption style={{ fontSize: 12, color: '#555' }}>{alt}</figcaption> : null}
    </figure>
  );
}
