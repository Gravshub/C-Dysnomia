// SPDX-License-Identifier: Sharia
pragma solidity ^0.8.21;
import "../dan/interfaces/01b_chointerface.sol";
import "../dan/interfaces/03b_qinginterface.sol";
import "../../interfaces/heckeinterface.sol";

interface MAPINTERFACE {
    function maxSupply() external view returns(uint256);
    function Rename(string memory newName, string memory newSymbol) external;
    function GetMarketRate(address _a) external view returns(uint256);
    function Purchase(address _t, uint256 _a) external;
    function Redeem(address _t, uint256 _a) external;
    function name() external view returns (string memory);
    function symbol() external view returns (string memory);
    function decimals() external view returns (uint8);
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function addOwner(address newOwner) external;
    function renounceOwnership(address toRemove) external;
    function owner(address cOwner) external view returns (bool);
    function mintToCap() external;
    function Type() external view returns (string memory);
    function Cho() external view returns (CHOINTERFACE);
    function Map() external view returns (HECKE);
    function Offset() external view returns (uint256);
    function GetMapQing(int256 Latitude, int256 Longitude) external view returns (QINGINTERFACE);
    function hasOwner(address _contract) external view returns (bool does);
    function has(address _contract, string memory what) external view returns (bool does);
    function Forbidden(address Asset) external view returns (bool);
    function Forbid(address Token, bool Disallow) external;
    function GetQing(uint256 Waat) external view returns (QINGINTERFACE);
    function New(address Integrative) external returns(QINGINTERFACE Mu);
}