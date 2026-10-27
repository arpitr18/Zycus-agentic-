import { createContext,useContext,useState,useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api,send,setCsrf } from './api';
const AuthContext=createContext(null);
export function AuthProvider({children}){const [user,setUser]=useState(null),[loading,setLoading]=useState(true);const cache=useQueryClient();
useEffect(()=>{api('/auth/me').then(data=>{setUser(data.user);setCsrf(data.csrf_token)}).catch(()=>{}).finally(()=>setLoading(false));const expired=()=>{setUser(null);setCsrf('');cache.clear()};window.addEventListener('session-expired',expired);return()=>window.removeEventListener('session-expired',expired)},[cache]);
async function login(email,password){const data=await send('/auth/login',{email,password});setCsrf(data.csrf_token);cache.clear();setUser(data.user)}
async function logout(){await send('/auth/logout',{});setCsrf('');setUser(null);cache.clear()}
return <AuthContext.Provider value={{user,loading,login,logout,isManager:user?.role==='manager'||user?.role==='admin',isAdmin:user?.role==='admin'}}>{children}</AuthContext.Provider>}
export const useAuth=()=>useContext(AuthContext);
