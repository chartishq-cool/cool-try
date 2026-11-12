import { createHash, timingSafeEqual } from 'crypto';
import type { NextApiRequest, NextApiResponse } from 'next';

export function requireScanAccess(req: NextApiRequest, res: NextApiResponse) {
  const secret = process.env.ARGUS_ACCESS_KEY;
  if (!secret) {
    res.status(503).json({ error: 'Scan controls need ARGUS_ACCESS_KEY in the deployment settings.' });
    return false;
  }
  const provided = req.headers['x-argus-key'];
  const hash = (text: string) => createHash('sha256').update(text).digest();
  if (typeof provided !== 'string' || !timingSafeEqual(hash(secret), hash(provided))) {
    res.status(401).json({ error: 'Enter your ARGUS access key to use scan controls.' });
    return false;
  }
  return true;
}
