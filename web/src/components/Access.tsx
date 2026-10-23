import { createContext, useContext } from 'react';

export const ReviewAccess = createContext('engineer');
export function useReviewOnly() { return ['reviewer', 'viewer'].includes(useContext(ReviewAccess)); }
export function useCanReview() { return ['owner', 'admin', 'manager', 'engineer', 'reviewer'].includes(useContext(ReviewAccess)); }
