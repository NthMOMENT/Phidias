use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod phidias_escrow {
    use super::*;

    pub fn initialize_escrow(ctx: Context<InitializeEscrow>, amount: u64, file_hash: u64) -> Result<()> {
        ctx.accounts.escrow.client = ctx.accounts.client.key();
        ctx.accounts.escrow.agent = ctx.accounts.agent.key();
        ctx.accounts.escrow.amount = amount;
        ctx.accounts.escrow.file_hash = file_hash;
        ctx.accounts.escrow.is_released = false;
        Ok(())
    }

    pub fn release_escrow(ctx: Context<ReleaseEscrow>, order_id: u64, delivered_hash: u64) -> Result<()> {
        require!(ctx.accounts.escrow.file_hash == delivered_hash, ErrorCode::HashMismatch);
        require!(!(ctx.accounts.escrow.is_released), ErrorCode::AlreadyReleased);
        let cpi_accounts = anchor_lang::system_program::Transfer {
            from: ctx.accounts.escrow.to_account_info(),
            to: ctx.accounts.agent.to_account_info(),
        };
        let cpi_program = ctx.accounts.system_program.to_account_info();
        anchor_lang::system_program::transfer(CpiContext::new(cpi_program, cpi_accounts), ctx.accounts.escrow.amount)?;
        ctx.accounts.escrow.is_released = true;
        emit!(EscrowReleased {
            order_id: order_id,
            file_hash: delivered_hash,
        });
        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializeEscrow<'info> {
    #[account(init, payer = client, space = 8 + 32 + 32 + 8 + 8 + 1)]
    pub escrow: Account<'info, Escrow>,
    #[account(mut)]
    pub client: Signer<'info>,
    pub agent: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ReleaseEscrow<'info> {
    #[account(mut)]
    pub escrow: Account<'info, Escrow>,
    pub client: Signer<'info>,
    #[account(mut)]
    pub agent: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[account]
pub struct Escrow {
    pub client: Pubkey,
    pub agent: Pubkey,
    pub amount: u64,
    pub file_hash: u64,
    pub is_released: bool,
}

#[event]
pub struct EscrowReleased {
    pub order_id: u64,
    pub file_hash: u64,
}

#[error_code]
pub enum ErrorCode {
    #[msg("HashMismatch")]
    HashMismatch,
    #[msg("AlreadyReleased")]
    AlreadyReleased,
}
