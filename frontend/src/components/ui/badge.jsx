import { cn } from '@/lib/utils';
export function Badge({className,children,tone='slate'}){return <span className={cn('badge',`badge-${tone}`,className)}>{children}</span>}
